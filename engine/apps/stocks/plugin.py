from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from PIL import Image

from canvas.base import Canvas
from plugin_base import DisplayApp
from libraries.canvas_utils.library import blit
from libraries.yahoo_finance.library import YahooFinanceLibrary, PRESET_GROUPS, INDEX_SYMBOLS, TICKER_DOMAIN
from libraries.text_renderer.library import TextRendererLibrary, FONTS_DIR

_STOCKS_FONT = FONTS_DIR / "LoRes" / "LoRes12OT-Regular.ttf"


# ── Colors ────────────────────────────────────────────────────────────────────

_COLOR_UP   = (80, 220, 80)
_COLOR_DOWN = (220, 80, 80)
_COLOR_SYM  = (200, 200, 200)
_COLOR_DIM  = (100, 100, 100)


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
    name: ClassVar[str] = "Stock Ticker"
    description: ClassVar[str] = (
        "Live prices and % change from Yahoo Finance — marquee or paginated, "
        "with company icons and curated preset groups"
    )
    icon: ClassVar[str] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="3,18 8,11 13,14 20,5"/><polyline points="16,5 20,5 20,9"/></svg>'
    )
    libraries: ClassVar[list[str]] = ["yahoo_finance", "text_renderer"]
    global_config_schema: ClassVar[dict[str, Any]] = {}
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Stock Ticker",
        "properties": {
            "source": {
                "type": "string",
                "title": "Data source",
                "enum": [
                    "custom", "tech", "largest_market_cap",
                    "finance", "healthcare", "energy",
                    "sp500", "nasdaq", "dow",
                ],
                "default": "custom",
            },
            "symbols": {
                "type": "array",
                "title": "Ticker symbols (custom source only)",
                "items": {"type": "string"},
                "default": ["AAPL", "MSFT", "GOOGL"],
            },
            "show_icons": {
                "type": "boolean",
                "title": "Show company icons",
                "default": True,
            },
            "display_mode": {
                "type": "string",
                "title": "Display mode",
                "enum": ["marquee", "paginate"],
                "default": "marquee",
            },
            "rows": {
                "type": "integer",
                "title": "Rows",
                "default": 1,
                "minimum": 1,
                "maximum": 8,
            },
            "price_display_interval": {
                "type": "integer",
                "title": "Price / % switch interval (frames)",
                "default": 90,
                "minimum": 10,
            },
            "frames_per_page": {
                "type": "integer",
                "title": "Frames per page (paginate only)",
                "default": 90,
                "minimum": 15,
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

        self._quotes: list[dict[str, Any]] = []
        self._logos: dict[str, Image.Image | None] = {}
        self._logos_fetched: set[str] = set()

        self._marquee_pct_rows: list[Image.Image | None] = []
        self._marquee_dol_rows: list[Image.Image | None] = []
        self._row_widths: list[int] = []
        self._row_offsets: list[float] = []
        self._row_speeds: list[float] = []

        self._page_cache: dict[tuple[bool, int], Image.Image] = {}

        self._show_pct: bool = True
        self._alt_counter: int = 0
        self._page: int = 0
        self._page_counter: int = 0

    def _rt(self, text: str, color: tuple[int, int, int], size: int, **kwargs) -> Image.Image:
        return self._renderer.render_lores(text, color, size, font_path=_STOCKS_FONT, **kwargs)

    async def on_activate(self) -> None:
        self._show_pct = True
        self._alt_counter = 0
        self._page = 0
        self._page_counter = 0
        self._row_offsets = []
        if self._quotes:
            self._build_images()

    # ── Data fetching ──────────────────────────────────────────────────────────

    def _get_symbols(self) -> list[str]:
        source = self.config.get("source", "custom")
        if source in PRESET_GROUPS:
            return PRESET_GROUPS[source]
        if source in INDEX_SYMBOLS:
            return INDEX_SYMBOLS[source]
        return list(self.config.get("symbols", ["AAPL", "MSFT", "GOOGL"]))

    async def fetch_data(self) -> None:
        symbols = self._get_symbols()
        show_icons = bool(self.config.get("show_icons", True))

        quotes = await self._yahoo.fetch_quotes(symbols)
        if quotes:
            self._quotes = quotes

        if show_icons:
            new_syms = [s for s in symbols if s not in self._logos_fetched]
            if new_syms:
                logo_results = await asyncio.gather(
                    *[self._yahoo.fetch_logo(s) for s in new_syms],
                    return_exceptions=True,
                )
                for sym, logo in zip(new_syms, logo_results):
                    self._logos[sym] = logo if isinstance(logo, Image.Image) else None
                    self._logos_fetched.add(sym)

        self._page_cache.clear()
        self._build_images()

    # ── Layout ─────────────────────────────────────────────────────────────────

    def _compute_layout(self) -> dict[str, Any]:
        h = self.canvas.height
        rows = max(1, int(self.config.get("rows", 1)))
        show_icons = bool(self.config.get("show_icons", True))

        row_h = max(8, h // rows)
        text_h = max(self._renderer.base_font_h, round(row_h * 0.65))
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
        if not self._quotes:
            return
        layout = self._compute_layout()
        n_rows = layout["n_rows"]

        self._marquee_pct_rows, self._marquee_dol_rows = self._render_both_marquees(layout)
        self._row_widths = [img.width if img else 0 for img in self._marquee_pct_rows]

        if len(self._row_offsets) != n_rows:
            cw = self.canvas.width
            self._row_offsets = [float(cw) for _ in range(n_rows)]

        if n_rows <= 1:
            self._row_speeds = [2.0]
        else:
            self._row_speeds = [2.0 + 1.5 * i / (n_rows - 1) for i in range(n_rows)]

        self._page_cache.clear()

    def _format_change(self, q: dict[str, Any], show_pct: bool) -> str:
        if show_pct:
            return f"{abs(q['change_pct']):.1f}%"
        return f"${abs(q['dollar_change']):.2f}"

    def _render_both_marquees(
        self, layout: dict
    ) -> tuple[list[Image.Image | None], list[Image.Image | None]]:
        if not self._quotes:
            return [], []

        n_rows = layout["n_rows"]
        row_quotes: list[list[dict[str, Any]]] = [[] for _ in range(n_rows)]
        for i, q in enumerate(self._quotes):
            row_quotes[i % n_rows].append(q)

        pct_rows: list[Image.Image | None] = []
        dol_rows: list[Image.Image | None] = []
        for quotes_in_row in row_quotes:
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
        spacer = max(10, text_h * 2)

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
        rows = layout["n_rows"]
        gap = max(2, text_h // 5)
        w, h = self.canvas.width, self.canvas.height

        img = Image.new("RGB", (w, h), (0, 0, 0))
        start = page * rows

        for i, q in enumerate(self._quotes[start : start + rows]):
            row_top = i * row_h
            x = 2

            up = q["change_pct"] >= 0
            color = _quote_color(q["change_pct"])
            cap_h = self._rt("A$%", _COLOR_SYM, text_h).height
            sym_img = self._rt(q["symbol"] + " ", _COLOR_SYM, text_h, fixed_h=cap_h)
            prc_img = self._rt(f"${q['price']:.2f} ", color, text_h, fixed_h=cap_h)
            chg_img = self._rt(self._format_change(q, show_pct), color, text_h, fixed_h=cap_h)
            arr_img = self._renderer.arrow_img(up, max(3, round(cap_h * 2 / 3)), color)

            def vc(item_h: int) -> int:
                return row_top + (row_h - item_h) // 2

            logo = self._logos.get(q["symbol"]) if icon_size > 0 else None
            if logo is not None:
                resized = logo.resize((icon_size, icon_size), Image.LANCZOS)
                _composite_icon(img, resized, x, vc(icon_size))
                x += icon_size + gap

            img.paste(sym_img, (x, vc(cap_h)))
            x += sym_img.width

            img.paste(prc_img, (x, vc(cap_h)))
            x += prc_img.width

            img.paste(arr_img, (x, vc(arr_img.height)))
            x += arr_img.width + gap

            if x + chg_img.width <= w:
                img.paste(chg_img, (x, vc(cap_h)))

        return img

    # ── Rendering ──────────────────────────────────────────────────────────────

    async def render_frame(self) -> None:
        if not self._quotes:
            self._draw_loading()
            return

        price_interval = int(self.config.get("price_display_interval", 90))
        display_mode = self.config.get("display_mode", "marquee")

        self._alt_counter += 1
        if self._alt_counter >= price_interval:
            self._alt_counter = 0
            self._show_pct = not self._show_pct

        if display_mode == "marquee":
            self._render_marquee_frame()
        else:
            self._render_paginate_frame()

    def _blit_row(self, img: Image.Image, x_offset: int, y_start: int, row_h: int) -> None:
        data = img.tobytes()
        iw, ih = img.size
        cw = self.canvas.width
        ch = self.canvas.height
        src_h = min(ih, row_h)

        dst_x_start = max(0, x_offset)
        dst_x_end = min(cw, x_offset + iw)

        for dst_x in range(dst_x_start, dst_x_end):
            src_x = dst_x - x_offset
            for src_y in range(src_h):
                dst_y = y_start + src_y
                if dst_y >= ch:
                    break
                idx = (src_y * iw + src_x) * 3
                self.canvas.set_pixel(dst_x, dst_y, data[idx], data[idx + 1], data[idx + 2])

    def _render_marquee_frame(self) -> None:
        if not self._marquee_pct_rows:
            self._build_images()
        if not self._marquee_pct_rows:
            return

        rows_imgs = self._marquee_pct_rows if self._show_pct else self._marquee_dol_rows
        n_rows = len(rows_imgs)
        row_h = self.canvas.height // n_rows

        for i, img in enumerate(rows_imgs):
            if img is None:
                continue
            row_y = i * row_h
            offset = int(self._row_offsets[i])
            self._blit_row(img, offset, row_y, row_h)
            self._row_offsets[i] -= self._row_speeds[i]
            if self._row_offsets[i] < -self._row_widths[i]:
                self._row_offsets[i] = float(self.canvas.width)

    def _render_paginate_frame(self) -> None:
        layout = self._compute_layout()
        rows = layout["n_rows"]
        frames_per_pge = int(self.config.get("frames_per_page", 90))
        max_pages = max(1, (len(self._quotes) + rows - 1) // rows)

        self._page_counter += 1
        if self._page_counter >= frames_per_pge:
            self._page_counter = 0
            self._page = (self._page + 1) % max_pages

        key = (self._show_pct, self._page)
        if key not in self._page_cache:
            self._page_cache[key] = self._build_page_image(layout, self._show_pct, self._page)

        blit(self.canvas, self._page_cache[key])

    def _draw_loading(self) -> None:
        msg_img = self._rt("Loading...", _COLOR_DIM, 1)
        img = Image.new("RGB", (self.canvas.width, self.canvas.height))
        x = (self.canvas.width - msg_img.width) // 2
        y = (self.canvas.height - msg_img.height) // 2
        img.paste(msg_img, (x, y))
        blit(self.canvas, img)
