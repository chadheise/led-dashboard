from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from PIL import Image, ImageDraw

from canvas.base import Canvas
from app_base import DisplayApp
from grid import SizeConstraints, split_vertical
from marquee import Marquee
from libraries.canvas_utils.library import blit
from libraries.yahoo_finance.library import YahooFinanceLibrary, PRESET_GROUPS
from libraries.text_renderer.library import TextRendererLibrary


# ── Colors ────────────────────────────────────────────────────────────────────

_COLOR_UP   = (80, 220, 80)
_COLOR_DOWN = (220, 80, 80)
_COLOR_SYM  = (200, 200, 200)
_COLOR_DIM  = (100, 100, 100)

_ALL_SOURCES = [
    "custom", "tech", "largest_market_cap", "finance", "healthcare", "energy",
    "sp500", "nasdaq", "dow",
]


def _quote_color(change_pct: float) -> tuple[int, int, int]:
    return _COLOR_UP if change_pct >= 0 else _COLOR_DOWN


def _composite_icon(base: Image.Image, icon: Image.Image, x: int, y: int) -> None:
    """Paste an RGBA icon onto an RGB base image using its alpha channel."""
    icon_rgba = icon.convert("RGBA")
    bg = Image.new("RGBA", icon_rgba.size, (0, 0, 0, 255))
    bg.alpha_composite(icon_rgba)
    base.paste(bg.convert("RGB"), (x, y))


class StocksApp(DisplayApp):
    id: ClassVar[str] = "stocks"
    name: ClassVar[str] = "Stocks"
    description: ClassVar[str] = (
        "Live prices and % change from Yahoo Finance — marquee, paginated, or chart view, "
        "with per-row data streams and company logos"
    )
    icon: ClassVar[str] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="3,18 8,11 13,14 20,5"/><polyline points="16,5 20,5 20,9"/></svg>'
    )
    libraries: ClassVar[list[str]] = ["yahoo_finance", "text_renderer"]
    size_constraints: ClassVar[SizeConstraints] = SizeConstraints(min_width=64, min_height=32)
    global_config_schema: ClassVar[dict[str, Any]] = {}
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Stocks",
        "properties": {
            "streams": {
                "type": "array",
                "title": "Data streams (one per row)",
                "x-input-type": "stream-list",
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "enum": _ALL_SOURCES,
                            "default": "custom",
                        },
                        "symbols": {
                            "type": "array",
                            "items": {"type": "string"},
                            "default": [],
                        },
                    },
                },
                "default": [
                    {"source": "custom", "symbols": ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "TSLA", "NVDA"]}
                ],
            },
            "show_icons": {
                "type": "boolean",
                "title": "Show company logos",
                "default": True,
            },
            "display_mode": {
                "type": "string",
                "title": "Display mode",
                "enum": ["marquee", "paginate", "chart"],
                "default": "marquee",
            },
            "price_display_interval": {
                "type": "integer",
                "title": "Price / % switch interval (frames)",
                "default": 90,
                "minimum": 10,
            },
            "frames_per_page": {
                "type": "integer",
                "title": "Frames per page (paginate / chart)",
                "default": 90,
                "minimum": 15,
            },
            "chart_time_frame": {
                "type": "string",
                "title": "Chart time frame",
                "enum": ["1W", "1M", "3M", "6M", "1Y"],
                "default": "1M",
            },
            "stocks_per_screen": {
                "type": "integer",
                "title": "Stocks per screen",
                "default": 1,
                "minimum": 1,
                "maximum": 4,
            },
            "chart_split_direction": {
                "type": "string",
                "title": "Chart split direction",
                "enum": ["horizontal", "vertical"],
                "default": "horizontal",
            },
            "refresh_interval": {
                "type": "number",
                "title": "Refresh interval (s)",
                "default": 60,
                "minimum": 10,
            },
        },
        "required": [],
    }

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def __init__(
        self,
        config: dict[str, Any],
        canvas: Canvas,
        global_config: dict[str, Any] | None = None,
        library_configs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(config, canvas, global_config, library_configs)
        self._yahoo = YahooFinanceLibrary(self.library_configs.get("yahoo_finance", {}))
        self._renderer = TextRendererLibrary(self.library_configs.get("text_renderer", {}))

        # Per-stream quote lists (one list per row/stream)
        self._stream_quotes: list[list[dict[str, Any]]] = []
        self._logos: dict[str, Image.Image | None] = {}
        self._logos_fetched: set[str] = set()

        # Marquee state (one entry per stream/row)
        self._marquee_pct_rows: list[Image.Image | None] = []
        self._marquee_dol_rows: list[Image.Image | None] = []
        self._row_marquees: list[Marquee] = []

        # Paginate state
        self._page_cache: dict[tuple[bool, int], Image.Image] = {}

        # Chart state
        self._chart_data: dict[str, dict[str, Any]] = {}
        self._chart_page: int = 0
        self._chart_page_counter: int = 0

        # Shared display state
        self._show_pct: bool = True
        self._alt_counter: int = 0
        self._page: int = 0
        self._page_counter: int = 0

    def _rt(self, text: str, color: tuple[int, int, int], size: int, **kwargs) -> Image.Image:
        return self._renderer.render_text(text, color, size, bold=True, **kwargs)

    def _get_streams(self) -> list[dict[str, Any]]:
        """Return stream configs, migrating old single-source format if needed."""
        streams = self.config.get("streams")
        if streams:
            return streams
        # Backward-compat: old config used top-level source + symbols
        source = self.config.get("source", "custom")
        symbols = self.config.get("symbols", ["AAPL", "MSFT", "GOOGL"])
        return [{"source": source, "symbols": symbols}]

    async def on_activate(self) -> None:
        self._show_pct = True
        self._alt_counter = 0
        self._page = 0
        self._page_counter = 0
        self._chart_page = 0
        self._chart_page_counter = 0
        self._row_marquees = []
        await self.fetch_data()

    # ── Data fetching ──────────────────────────────────────────────────────────

    async def _get_stream_symbols(self, stream: dict[str, Any]) -> list[str]:
        source = stream.get("source", "custom")
        if source == "sp500":
            return ["^GSPC"] + await self._yahoo.fetch_sp500_symbols()
        if source == "nasdaq":
            return ["^IXIC"] + self._yahoo.fetch_nasdaq100_symbols()
        if source == "dow":
            return ["^DJI"] + self._yahoo.fetch_dow30_symbols()
        if source == "largest_market_cap":
            return await self._yahoo.fetch_largest_market_cap(n=10)
        if source in PRESET_GROUPS:
            return PRESET_GROUPS[source]
        return list(stream.get("symbols", ["AAPL", "MSFT", "GOOGL"]))

    async def fetch_data(self) -> None:
        streams = self._get_streams()
        show_icons = bool(self.config.get("show_icons", True))
        display_mode = self.config.get("display_mode", "marquee")
        time_frame = self.config.get("chart_time_frame", "1M")

        # Resolve symbols for each stream in parallel
        all_symbols_per_stream = await asyncio.gather(
            *[self._get_stream_symbols(s) for s in streams],
            return_exceptions=False,
        )

        # Fetch quotes for each stream in parallel
        quote_results = await asyncio.gather(
            *[self._yahoo.fetch_quotes(syms) for syms in all_symbols_per_stream],
            return_exceptions=True,
        )

        new_stream_quotes: list[list[dict[str, Any]]] = []
        for i, result in enumerate(quote_results):
            if isinstance(result, list) and result:
                new_stream_quotes.append(result)
            elif i < len(self._stream_quotes) and self._stream_quotes[i]:
                new_stream_quotes.append(self._stream_quotes[i])
            else:
                new_stream_quotes.append([])

        self._stream_quotes = new_stream_quotes

        # Fetch logos for all unique symbols
        if show_icons:
            all_symbols: list[str] = []
            for syms in all_symbols_per_stream:
                all_symbols.extend(syms)
            new_syms = [s for s in dict.fromkeys(all_symbols) if s not in self._logos_fetched]
            if new_syms:
                logo_results = await asyncio.gather(
                    *[self._yahoo.fetch_logo(s) for s in new_syms],
                    return_exceptions=True,
                )
                for sym, logo in zip(new_syms, logo_results):
                    self._logos[sym] = logo if isinstance(logo, Image.Image) else None
                    self._logos_fetched.add(sym)

        # Fetch chart data for all streams if in chart mode
        if display_mode == "chart" and all_symbols_per_stream:
            seen: set[str] = set()
            chart_syms: list[str] = []
            for syms in all_symbols_per_stream:
                for s in syms:
                    if s not in seen:
                        seen.add(s)
                        chart_syms.append(s)
            chart_results = await asyncio.gather(
                *[self._yahoo.fetch_chart_data(s, time_frame) for s in chart_syms],
                return_exceptions=True,
            )
            for sym, data in zip(chart_syms, chart_results):
                if isinstance(data, dict):
                    self._chart_data[sym] = data

        self._page_cache.clear()
        self._build_images()

    # ── Layout ─────────────────────────────────────────────────────────────────

    def _compute_layout(self) -> dict[str, Any]:
        h = self.canvas.height
        streams = self._get_streams()
        rows = max(1, len(streams))
        show_icons = bool(self.config.get("show_icons", True))

        row_h = max(8, h // rows)
        ratio = 0.40 if rows == 1 else 0.65
        text_h = max(self._renderer.min_pixel_font_size, round(row_h * ratio))
        arrow_size = text_h
        icon_size = text_h if (show_icons and text_h >= 12) else 0

        return {
            "row_h": row_h,
            "n_rows": rows,
            "text_h": text_h,
            "arrow_size": arrow_size,
            "icon_size": icon_size,
        }

    # ── Image building ─────────────────────────────────────────────────────────

    def _build_images(self) -> None:
        if not self._stream_quotes:
            return
        layout = self._compute_layout()
        n_rows = layout["n_rows"]

        self._marquee_pct_rows, self._marquee_dol_rows = self._render_both_marquees(layout)

        if len(self._row_marquees) != n_rows:
            if n_rows <= 1:
                speeds = [2.0]
            else:
                speeds = [2.0 + 1.5 * i / (n_rows - 1) for i in range(n_rows)]
            self._row_marquees = [
                Marquee(direction="left", speed=s, loop=True) for s in speeds
            ]

        self._page_cache.clear()

    def _format_change(self, q: dict[str, Any], show_pct: bool) -> str:
        if show_pct:
            return f"{abs(q['change_pct']):.1f}%"
        return f"${abs(q['dollar_change']):.2f}"

    def _render_both_marquees(
        self, layout: dict
    ) -> tuple[list[Image.Image | None], list[Image.Image | None]]:
        if not self._stream_quotes:
            return [], []

        pct_rows: list[Image.Image | None] = []
        dol_rows: list[Image.Image | None] = []
        for quotes_in_row in self._stream_quotes:
            if not quotes_in_row:
                pct_rows.append(None)
                dol_rows.append(None)
            else:
                p, d = self._render_row_pair(layout, quotes_in_row)
                pct_rows.append(p)
                dol_rows.append(d)

        return pct_rows, dol_rows

    def _render_row_pair(
        self, layout: dict, quotes: list[dict[str, Any]]
    ) -> tuple[Image.Image | None, Image.Image | None]:
        if not quotes:
            return None, None

        text_h = layout["text_h"]
        icon_size = layout["icon_size"]
        h = layout["row_h"]
        gap = max(2, text_h // 5)
        spacer = gap * 2

        cap_h = self._rt("A$%", _COLOR_SYM, text_h).height

        def vc(item_h: int) -> int:
            return max(0, (h - item_h) // 2)

        entries: list[dict[str, Any]] = []
        total_w = 0
        for q in quotes:
            up = q["change_pct"] >= 0
            color = _quote_color(q["change_pct"])

            sym_img = self._rt(q["symbol"] + " ", _COLOR_SYM, text_h, fixed_h=cap_h)
            prc_img = self._rt(f"${q['price']:.2f} ", color, text_h, fixed_h=cap_h)
            arr_img = self._renderer.arrow_img(up, max(3, round(cap_h * 2 / 3)), color)

            chg_pct_img = self._rt(self._format_change(q, True), color, text_h, fixed_h=cap_h)
            chg_dol_img = self._rt(self._format_change(q, False), color, text_h, fixed_h=cap_h)
            chg_slot_w = max(chg_pct_img.width, chg_dol_img.width)

            logo = self._logos.get(q["symbol"]) if icon_size > 0 else None
            icon_w = icon_size + gap if logo is not None else 0
            entry_w = icon_w + sym_img.width + prc_img.width + arr_img.width + gap + chg_slot_w + spacer

            entries.append({
                "q": q, "sym_img": sym_img, "prc_img": prc_img, "arr_img": arr_img,
                "chg_pct_img": chg_pct_img, "chg_dol_img": chg_dol_img,
                "chg_slot_w": chg_slot_w, "logo": logo, "icon_w": icon_w,
            })
            total_w += entry_w

        if total_w <= 0:
            return None, None

        img_pct = Image.new("RGB", (total_w, h), (0, 0, 0))
        img_dol = Image.new("RGB", (total_w, h), (0, 0, 0))
        x = 0

        for e in entries:
            for img in (img_pct, img_dol):
                ex = x
                if e["logo"] is not None and icon_size > 0:
                    resized = e["logo"].resize((icon_size, icon_size), Image.LANCZOS)
                    _composite_icon(img, resized, ex, vc(icon_size))
                    ex += icon_size + gap
                img.paste(e["sym_img"], (ex, vc(cap_h))); ex += e["sym_img"].width
                img.paste(e["prc_img"], (ex, vc(cap_h))); ex += e["prc_img"].width
                img.paste(e["arr_img"], (ex, vc(e["arr_img"].height))); ex += e["arr_img"].width + gap

            chg_x = x + e["icon_w"] + e["sym_img"].width + e["prc_img"].width + e["arr_img"].width + gap
            img_pct.paste(e["chg_pct_img"], (chg_x, vc(cap_h)))
            img_dol.paste(e["chg_dol_img"], (chg_x, vc(cap_h)))

            x += e["icon_w"] + e["sym_img"].width + e["prc_img"].width + e["arr_img"].width + gap + e["chg_slot_w"] + spacer

        return img_pct, img_dol

    def _build_page_image(self, layout: dict, show_pct: bool, page: int) -> Image.Image:
        text_h = layout["text_h"]
        icon_size = layout["icon_size"]
        row_h = layout["row_h"]
        w, h = self.canvas.width, self.canvas.height

        img = Image.new("RGB", (w, h), (0, 0, 0))

        for stream_idx, stream_quotes in enumerate(self._stream_quotes):
            if not stream_quotes:
                continue
            q = stream_quotes[page % len(stream_quotes)]
            row_top = stream_idx * row_h
            x = 2

            up = q["change_pct"] >= 0
            color = _quote_color(q["change_pct"])
            cap_h = self._rt("A$%", _COLOR_SYM, text_h).height
            sym_img = self._rt(q["symbol"] + " ", _COLOR_SYM, text_h, fixed_h=cap_h)
            prc_img = self._rt(f"${q['price']:.2f} ", color, text_h, fixed_h=cap_h)
            chg_img = self._rt(self._format_change(q, show_pct), color, text_h, fixed_h=cap_h)
            arr_img = self._renderer.arrow_img(up, max(3, round(cap_h * 2 / 3)), color)

            def vc(item_h: int, top: int = row_top) -> int:
                return top + (row_h - item_h) // 2

            logo = self._logos.get(q["symbol"]) if icon_size > 0 else None
            if logo is not None:
                resized = logo.resize((icon_size, icon_size), Image.LANCZOS)
                _composite_icon(img, resized, x, vc(icon_size))
                x += icon_size + max(2, text_h // 5)

            img.paste(sym_img, (x, vc(cap_h)))
            x += sym_img.width
            img.paste(prc_img, (x, vc(cap_h)))
            x += prc_img.width
            img.paste(arr_img, (x, vc(arr_img.height)))
            x += arr_img.width + max(2, text_h // 5)
            if x + chg_img.width <= w:
                img.paste(chg_img, (x, vc(cap_h)))

        return img

    # ── Chart rendering ────────────────────────────────────────────────────────

    def _render_chart_slot(
        self,
        img: Image.Image,
        data: dict[str, Any],
        x0: int,
        y0: int,
        slot_w: int,
        slot_h: int,
    ) -> None:
        closes = data.get("closes", [])
        symbol = data.get("symbol", "")
        price = data.get("current_price", 0.0)
        change_pct = data.get("change_pct", 0.0)
        dollar_change = data.get("dollar_change", 0.0)

        up = change_pct >= 0
        color = _COLOR_UP if up else _COLOR_DOWN

        # Text size driven by slot height only; layout adapts to slot width below
        base = self._renderer.min_pixel_font_size
        text_h = max(base, slot_h // 5)
        show_icons = bool(self.config.get("show_icons", True))
        icon_size = text_h if (show_icons and text_h >= 12) else 0
        gap = max(2, text_h // 5)
        logo = self._logos.get(symbol) if icon_size > 0 else None

        cap_h = self._rt("A$%", (255, 255, 255), text_h).height
        arr_img = self._renderer.arrow_img(up, max(3, round(cap_h * 2 / 3)), color)
        sym_img = self._rt(symbol + " ", (255, 255, 255), text_h, fixed_h=cap_h)
        prc_img = self._rt(f"${price:.2f} ", color, text_h, fixed_h=cap_h)
        chg_str = (
            f"{abs(change_pct):.2f}%"
            if self._show_pct
            else f"${abs(dollar_change):.2f}"
        )
        chg_img = self._rt(chg_str, color, text_h, fixed_h=cap_h)

        icon_w = icon_size + gap if logo is not None else 0
        arr_w = arr_img.width + gap

        def paste_arr(dst: Image.Image, ax: int, line_y: int, line_h: int) -> None:
            ay = line_y + (line_h - arr_img.height) // 2
            dst.paste(arr_img, (ax, ay))

        # logo_inner: reduce by 2px so there is at least 1px margin on all sides
        logo_inner = max(1, icon_size - 2) if logo is not None else 0

        # Choose single-line or two-line layout based on available width
        if icon_w + sym_img.width + prc_img.width + arr_w + chg_img.width <= slot_w:
            # Everything fits on one line
            header_h = max(cap_h, icon_size) if logo is not None else cap_h
            header_img = Image.new("RGB", (slot_w, header_h), (0, 0, 0))
            hx = 1  # 1px left margin before logo
            text_y = (header_h - cap_h) // 2
            if logo is not None:
                resized = logo.resize((logo_inner, logo_inner), Image.LANCZOS)
                logo_y = max(1, (header_h - logo_inner) // 2)
                _composite_icon(header_img, resized, hx, logo_y)
                hx += logo_inner + 1 + gap  # logo + 1px right margin + gap
            header_img.paste(sym_img, (hx, text_y)); hx += sym_img.width
            header_img.paste(prc_img, (hx, text_y)); hx += prc_img.width
            paste_arr(header_img, hx, text_y, cap_h); hx += arr_w
            header_img.paste(chg_img, (hx, text_y))
        else:
            # Two-line: [logo] symbol on line 1 / price + arrow + change on line 2
            header_h = cap_h * 2 + gap
            header_img = Image.new("RGB", (slot_w, header_h), (0, 0, 0))
            # Line 1
            hx = 1  # 1px left margin before logo
            if logo is not None:
                resized = logo.resize((logo_inner, logo_inner), Image.LANCZOS)
                logo_y = max(1, (cap_h - logo_inner) // 2)
                _composite_icon(header_img, resized, hx, logo_y)
                hx += logo_inner + 1 + gap
            header_img.paste(sym_img, (hx, 0))
            # Line 2
            hx = 0
            y2 = cap_h + gap
            header_img.paste(prc_img, (hx, y2)); hx += prc_img.width
            paste_arr(header_img, hx, y2, cap_h); hx += arr_w
            if hx + chg_img.width <= slot_w:
                header_img.paste(chg_img, (hx, y2))

        img.paste(header_img, (x0, y0))

        # Chart area
        chart_y0 = y0 + header_h + 1
        chart_h = slot_h - header_h - 1
        if chart_h <= 0 or len(closes) < 2:
            return

        min_p = min(closes)
        max_p = max(closes)
        price_range = max_p - min_p or 1.0
        n = len(closes)

        def scale_x(i: int) -> int:
            return x0 + int(i * (slot_w - 1) / (n - 1))

        def scale_y(p: float) -> int:
            return chart_y0 + int((1.0 - (p - min_p) / price_range) * (chart_h - 1))

        draw = ImageDraw.Draw(img)

        # Filled polygon (chart area under the line)
        poly_pts = [(scale_x(0), chart_y0 + chart_h)]
        for i, c in enumerate(closes):
            poly_pts.append((scale_x(i), scale_y(c)))
        poly_pts.append((scale_x(n - 1), chart_y0 + chart_h))

        fill_color = tuple(max(0, v - 120) for v in color)
        draw.polygon(poly_pts, fill=fill_color)  # type: ignore[arg-type]

        # Price line
        line_pts = [(scale_x(i), scale_y(c)) for i, c in enumerate(closes)]
        draw.line(line_pts, fill=color, width=1)

        # Time frame label — smallest non-bold text, white, composited without black box.
        _TF_LABELS = {"1W": "1 wk", "1M": "1 mo", "3M": "3 mo", "6M": "6 mo", "1Y": "1 yr"}
        tf_text = _TF_LABELS.get(self.config.get("chart_time_frame", "1M"), "")
        if tf_text:
            tf_img = self._renderer.render_text(tf_text, (255, 255, 255), base, bold=False)
            img.paste(tf_img, (x0 + slot_w - tf_img.width - 2, y0 + slot_h - tf_img.height - 1),
                      mask=tf_img.convert("L"))

    def _render_chart_frame(self) -> None:
        stocks_per_screen = max(1, min(4, int(self.config.get("stocks_per_screen", 1))))
        frames_per_page = int(self.config.get("frames_per_page", 90))
        direction = self.config.get("chart_split_direction", "horizontal")

        # Collect chart symbols from all streams (deduped, order preserved)
        if not self._stream_quotes or all(not sq for sq in self._stream_quotes):
            self._draw_loading()
            return

        seen: set[str] = set()
        chart_symbols: list[str] = []
        for sq in self._stream_quotes:
            for q in sq:
                if q["symbol"] not in seen:
                    seen.add(q["symbol"])
                    chart_symbols.append(q["symbol"])
        available = [s for s in chart_symbols if s in self._chart_data]
        if not available:
            self._draw_loading()
            return

        max_pages = max(1, (len(available) + stocks_per_screen - 1) // stocks_per_screen)
        self._chart_page_counter += 1
        if self._chart_page_counter >= frames_per_page:
            self._chart_page_counter = 0
            self._chart_page = (self._chart_page + 1) % max_pages

        start = self._chart_page * stocks_per_screen
        visible_syms = available[start : start + stocks_per_screen]
        n = len(visible_syms)

        w, h = self.canvas.width, self.canvas.height
        img = Image.new("RGB", (w, h), (0, 0, 0))

        if direction == "horizontal":
            slot_w = w // n
            for i, sym in enumerate(visible_syms):
                x0 = i * slot_w
                actual_w = slot_w if i < n - 1 else w - x0
                self._render_chart_slot(img, self._chart_data[sym], x0, 0, actual_w, h)
            draw = ImageDraw.Draw(img)
            for i in range(1, n):
                draw.line([(i * slot_w, 0), (i * slot_w, h - 1)], fill=(35, 35, 35))
        else:
            slot_h = h // n
            for i, sym in enumerate(visible_syms):
                y0 = i * slot_h
                actual_h = slot_h if i < n - 1 else h - y0
                self._render_chart_slot(img, self._chart_data[sym], 0, y0, w, actual_h)
            draw = ImageDraw.Draw(img)
            for i in range(1, n):
                draw.line([(0, i * slot_h), (w - 1, i * slot_h)], fill=(35, 35, 35))

        blit(self.canvas, img)

    # ── Rendering ──────────────────────────────────────────────────────────────

    async def render_frame(self) -> None:
        if not self._stream_quotes or all(not sq for sq in self._stream_quotes):
            self._draw_loading()
            return

        display_mode = self.config.get("display_mode", "marquee")
        frames_per_page = int(self.config.get("frames_per_page", 90))
        if display_mode in ("chart", "paginate"):
            price_interval = max(10, frames_per_page // 2)
        else:
            price_interval = int(self.config.get("price_display_interval", 90))

        self._alt_counter += 1
        if self._alt_counter >= price_interval:
            self._alt_counter = 0
            self._show_pct = not self._show_pct

        if display_mode == "marquee":
            self._render_marquee_frame()
        elif display_mode == "chart":
            self._render_chart_frame()
        else:
            self._render_paginate_frame()

    def _render_marquee_frame(self) -> None:
        if not self._marquee_pct_rows:
            self._build_images()
        if not self._marquee_pct_rows:
            return

        rows_imgs = self._marquee_pct_rows if self._show_pct else self._marquee_dol_rows
        n_rows = len(rows_imgs)
        row_regions = split_vertical(self.canvas, n_rows)

        for img, region, marquee in zip(rows_imgs, row_regions, self._row_marquees):
            if img is None:
                continue
            marquee.render(region, img)

    def _fit_text(
        self,
        text: str,
        color: tuple[int, int, int],
        max_h: int,
        max_w: int,
        bold: bool = True,
    ) -> Image.Image:
        """Render text, shrinking size proportionally until it fits max_w."""
        th = max(self._renderer.min_pixel_font_size, max_h)
        while True:
            rendered = self._renderer.render_text(text, color, th, bold=bold)
            if rendered.width <= max_w or th <= self._renderer.min_pixel_font_size:
                return rendered
            th = max(self._renderer.min_pixel_font_size, th * max_w // rendered.width)

    def _render_paginate_slot(
        self,
        img: Image.Image,
        q: dict[str, Any],
        x0: int,
        y0: int,
        slot_w: int,
        slot_h: int,
    ) -> None:
        show_icons = bool(self.config.get("show_icons", True))
        base = self._renderer.min_pixel_font_size
        up = q["change_pct"] >= 0
        color = _quote_color(q["change_pct"])
        white = (255, 255, 255)
        margin = 2

        def ctr(item_h: int, band_y: int, band_h: int) -> int:
            return band_y + max(0, (band_h - item_h) // 2)

        def place_logo(logo: Image.Image, target_h: int, lx: int, band_y: int, band_h: int) -> int:
            """Scale logo to target_h (aspect-ratio preserving), paste, return x advance."""
            iw, ih = logo.size
            scale = min(target_h / max(iw, 1), target_h / max(ih, 1))
            lw = max(1, round(iw * scale))
            lh = max(1, round(ih * scale))
            resized = logo.resize((lw, lh), Image.LANCZOS)
            _composite_icon(img, resized, lx, ctr(lh, band_y, band_h))
            return lw + max(2, target_h // 5)  # advance including gap

        # ── Measure what a single row costs at the height-ideal text size ─────────
        text_h = max(base, slot_h * 2 // 5)
        gap = max(2, text_h // 5)
        icon_size = text_h if (show_icons and text_h >= 12) else 0
        logo = self._logos.get(q["symbol"]) if icon_size > 0 else None
        icon_w = icon_size + gap if logo is not None else 0

        cap_h = self._rt("A$%", white, text_h).height
        sym_img = self._rt(q["symbol"] + " ", white, text_h, fixed_h=cap_h)
        prc_img = self._rt(f"${q['price']:.2f} ", color, text_h, fixed_h=cap_h)
        chg_img = self._rt(self._format_change(q, self._show_pct), color, text_h, fixed_h=cap_h)
        arr_img = self._renderer.arrow_img(up, max(3, round(cap_h * 2 / 3)), color)

        needed_1row = margin + icon_w + sym_img.width + prc_img.width + arr_img.width + gap + chg_img.width

        if needed_1row <= slot_w:
            # ── 1-row: everything fits at the ideal size ─────────────────────────
            px = x0 + margin

            def vc(item_h: int) -> int:
                return y0 + max(0, (slot_h - item_h) // 2)

            if logo is not None:
                px += place_logo(logo, icon_size, px, y0, slot_h)
            img.paste(sym_img, (px, vc(cap_h))); px += sym_img.width
            img.paste(prc_img, (px, vc(cap_h))); px += prc_img.width
            img.paste(arr_img, (px, vc(arr_img.height))); px += arr_img.width + gap
            img.paste(chg_img, (px, vc(cap_h)))

        elif slot_h >= 20:
            # ── 2-row: [logo] symbol / price + arrow + change ────────────────────
            row_h = slot_h // 2

            # Row 1 — logo + symbol
            r1_h = max(base, row_h * 3 // 4)
            r1_logo = self._logos.get(q["symbol"]) if (show_icons and r1_h >= base) else None
            icon_advance = 0
            r1_x = x0 + margin
            if r1_logo is not None:
                icon_advance = place_logo(r1_logo, r1_h, r1_x, y0, row_h)
            sym_max_w = slot_w - 2 * margin - icon_advance
            r1_sym = self._fit_text(q["symbol"], white, r1_h, sym_max_w)
            img.paste(r1_sym, (r1_x + icon_advance, ctr(r1_sym.height, y0, row_h)))

            # Row 2 — price + arrow + change
            r2_h = max(base, row_h * 3 // 4)
            r2_cap = self._rt("A$%", white, r2_h).height
            r2_prc = self._rt(f"${q['price']:.2f} ", color, r2_h, fixed_h=r2_cap)
            r2_arr = self._renderer.arrow_img(up, max(3, round(r2_cap * 2 / 3)), color)
            r2_gap = max(2, r2_h // 5)
            chg_budget = slot_w - 2 * margin - r2_prc.width - r2_arr.width - r2_gap
            r2_chg = self._fit_text(self._format_change(q, self._show_pct), color, r2_h, chg_budget)

            row2_y = y0 + row_h
            px = x0 + margin
            img.paste(r2_prc, (px, ctr(r2_cap, row2_y, row_h))); px += r2_prc.width
            img.paste(r2_arr, (px, ctr(r2_arr.height, row2_y, row_h))); px += r2_arr.width + r2_gap
            img.paste(r2_chg, (px, ctr(r2_chg.height, row2_y, row_h)))

        else:
            # ── Single row, very short slot — shrink to fit ───────────────────────
            while True:
                gap = max(2, text_h // 5)
                icon_size = text_h if (show_icons and text_h >= 12) else 0
                logo = self._logos.get(q["symbol"]) if icon_size > 0 else None
                icon_w = icon_size + gap if logo is not None else 0
                cap_h = self._rt("A$%", white, text_h).height
                sym_img = self._rt(q["symbol"] + " ", white, text_h, fixed_h=cap_h)
                prc_img = self._rt(f"${q['price']:.2f} ", color, text_h, fixed_h=cap_h)
                chg_img = self._rt(self._format_change(q, self._show_pct), color, text_h, fixed_h=cap_h)
                arr_img = self._renderer.arrow_img(up, max(3, round(cap_h * 2 / 3)), color)
                needed = margin + icon_w + sym_img.width + prc_img.width + arr_img.width + gap + chg_img.width
                if needed <= slot_w or text_h <= base:
                    break
                text_h = max(base, text_h * slot_w // needed)

            px = x0 + margin

            def vc(item_h: int) -> int:
                return y0 + max(0, (slot_h - item_h) // 2)

            if logo is not None:
                px += place_logo(logo, icon_size, px, y0, slot_h)
            img.paste(sym_img, (px, vc(cap_h))); px += sym_img.width
            img.paste(prc_img, (px, vc(cap_h))); px += prc_img.width
            img.paste(arr_img, (px, vc(arr_img.height))); px += arr_img.width + gap
            if px + chg_img.width <= x0 + slot_w:
                img.paste(chg_img, (px, vc(cap_h)))

    def _render_paginate_frame(self) -> None:
        stocks_per_screen = max(1, min(4, int(self.config.get("stocks_per_screen", 1))))
        direction = self.config.get("chart_split_direction", "horizontal")
        frames_per_page = int(self.config.get("frames_per_page", 90))

        self._page_counter += 1
        advance = self._page_counter >= frames_per_page
        if advance:
            self._page_counter = 0

        w, h = self.canvas.width, self.canvas.height
        img = Image.new("RGB", (w, h), (0, 0, 0))

        if stocks_per_screen == 1:
            # One stock per stream, streams stacked vertically — each stream pages independently
            active = [(sq, i) for i, sq in enumerate(self._stream_quotes) if sq]
            if not active:
                self._draw_loading()
                return
            if advance:
                self._page = (self._page + 1) % max(1, max(len(sq) for sq, _ in active))
            n = len(active)
            slot_h = h // n
            for j, (sq, _) in enumerate(active):
                q = sq[self._page % len(sq)]
                y0 = j * slot_h
                self._render_paginate_slot(img, q, 0, y0, w, slot_h if j < n - 1 else h - y0)
            if n > 1:
                draw = ImageDraw.Draw(img)
                for j in range(1, n):
                    draw.line([(0, j * slot_h), (w - 1, j * slot_h)], fill=(35, 35, 35))
        else:
            # N-up: show stocks_per_screen quotes at once, drawing from all streams combined
            quotes = [q for sq in self._stream_quotes for q in sq]
            if not quotes:
                self._draw_loading()
                return
            max_pages = max(1, (len(quotes) + stocks_per_screen - 1) // stocks_per_screen)
            if advance:
                self._page = (self._page + 1) % max_pages
            start = self._page * stocks_per_screen
            visible = quotes[start : start + stocks_per_screen]
            n = len(visible)

            if direction == "horizontal":
                slot_w = w // n
                for i, q in enumerate(visible):
                    x0 = i * slot_w
                    self._render_paginate_slot(img, q, x0, 0, slot_w if i < n - 1 else w - x0, h)
                if n > 1:
                    draw = ImageDraw.Draw(img)
                    for i in range(1, n):
                        draw.line([(i * slot_w, 0), (i * slot_w, h - 1)], fill=(35, 35, 35))
            else:
                slot_h = h // n
                for i, q in enumerate(visible):
                    y0 = i * slot_h
                    self._render_paginate_slot(img, q, 0, y0, w, slot_h if i < n - 1 else h - y0)
                if n > 1:
                    draw = ImageDraw.Draw(img)
                    for i in range(1, n):
                        draw.line([(0, i * slot_h), (w - 1, i * slot_h)], fill=(35, 35, 35))

        blit(self.canvas, img)

    def _draw_loading(self) -> None:
        msg_img = self._rt("Loading...", _COLOR_DIM, 1)
        img = Image.new("RGB", (self.canvas.width, self.canvas.height))
        x = (self.canvas.width - msg_img.width) // 2
        y = (self.canvas.height - msg_img.height) // 2
        img.paste(msg_img, (x, y))
        blit(self.canvas, img)
