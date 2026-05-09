from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Any, ClassVar

import httpx
from PIL import Image, ImageDraw

from canvas.base import Canvas
from plugin_base import DisplayApp
from plugins._helpers import blit, load_font


# ── Preset stock groupings ─────────────────────────────────────────────────────

PRESET_GROUPS: dict[str, list[str]] = {
    "tech": ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "TSLA", "AVGO", "ORCL", "CRM", "ADBE"],
    "largest_market_cap": ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "BRK-B", "TSLA", "AVGO", "JPM"],
    "finance": ["JPM", "BAC", "WFC", "GS", "MS", "BLK", "C", "USB", "AXP", "PNC"],
    "healthcare": ["LLY", "UNH", "JNJ", "ABBV", "MRK", "TMO", "ABT", "DHR", "AMGN", "PFE"],
    "energy": ["XOM", "CVX", "COP", "SLB", "EOG", "PSX", "MPC", "VLO", "OKE", "WMB"],
}

INDEX_SYMBOLS: dict[str, list[str]] = {
    "sp500": ["^GSPC"],
    "nasdaq": ["^IXIC"],
    "dow": ["^DJI"],
}

# Ticker symbol → primary web domain (for Clearbit Logo API)
TICKER_DOMAIN: dict[str, str] = {
    "AAPL": "apple.com",          "MSFT": "microsoft.com",     "GOOGL": "google.com",
    "GOOG": "google.com",         "AMZN": "amazon.com",         "META": "meta.com",
    "TSLA": "tesla.com",          "NVDA": "nvidia.com",         "AVGO": "broadcom.com",
    "ORCL": "oracle.com",         "CRM": "salesforce.com",      "ADBE": "adobe.com",
    "AMD": "amd.com",             "INTC": "intel.com",          "IBM": "ibm.com",
    "QCOM": "qualcomm.com",       "TXN": "ti.com",
    "JPM": "jpmorganchase.com",   "BAC": "bankofamerica.com",   "WFC": "wellsfargo.com",
    "GS": "gs.com",               "MS": "morganstanley.com",    "BLK": "blackrock.com",
    "C": "citi.com",              "USB": "usbank.com",          "AXP": "americanexpress.com",
    "PNC": "pnc.com",             "V": "visa.com",              "MA": "mastercard.com",
    "PYPL": "paypal.com",
    "LLY": "lilly.com",           "UNH": "unitedhealthgroup.com", "JNJ": "jnj.com",
    "ABBV": "abbvie.com",         "MRK": "merck.com",           "TMO": "thermofisher.com",
    "ABT": "abbott.com",          "DHR": "danaher.com",         "AMGN": "amgen.com",
    "PFE": "pfizer.com",          "MDT": "medtronic.com",       "BMY": "bms.com",
    "XOM": "exxonmobil.com",      "CVX": "chevron.com",         "COP": "conocophillips.com",
    "SLB": "slb.com",             "EOG": "eogresources.com",    "PSX": "phillips66.com",
    "MPC": "marathonpetroleum.com", "VLO": "valero.com",
    "NEE": "nexteraenergy.com",   "SO": "southerncompany.com",  "DUK": "duke-energy.com",
    "WMT": "walmart.com",         "HD": "homedepot.com",        "LOW": "lowes.com",
    "TGT": "target.com",          "COST": "costco.com",
    "MCD": "mcdonalds.com",       "SBUX": "starbucks.com",      "CMG": "chipotle.com",
    "NFLX": "netflix.com",        "DIS": "disney.com",          "CMCSA": "comcast.com",
    "T": "att.com",               "VZ": "verizon.com",
    "KO": "coca-cola.com",        "PEP": "pepsico.com",         "PG": "pg.com",
    "NKE": "nike.com",            "BA": "boeing.com",           "CAT": "caterpillar.com",
    "HON": "honeywell.com",       "GE": "ge.com",               "MMM": "3m.com",
    "F": "ford.com",              "GM": "gm.com",
    "BRK-B": "berkshirehathaway.com",
    "SPY": "ssga.com",            "QQQ": "invesco.com",         "IWM": "blackrock.com",
}

# Green / red / neutral colors for rendering
_COLOR_UP   = (80, 220, 80)
_COLOR_DOWN = (220, 80, 80)
_COLOR_SYM  = (200, 200, 200)
_COLOR_DIM  = (100, 100, 100)


def _up_down_arrow(change_pct: float) -> str:
    return "▲" if change_pct >= 0 else "▼"  # ▲ / ▼


def _quote_color(change_pct: float) -> tuple[int, int, int]:
    return _COLOR_UP if change_pct >= 0 else _COLOR_DOWN


def _measure_text(draw: ImageDraw.ImageDraw, text: str, font: Any) -> tuple[int, int]:
    """Return (width, height) of text rendered with font."""
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _text_y_center(row_top: int, row_h: int, text_h: int, ascent: int) -> int:
    """Vertical draw position to centre text in a row, correcting for ascent."""
    return row_top + (row_h - text_h) // 2 - ascent


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
                "title": "Rows per page (paginate only)",
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
            "scene_duration": {
                "type": "number",
                "title": "Scene duration (s)",
                "default": 60,
            },
        },
        "required": [],
    }

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def __init__(self, config: dict[str, Any], canvas: Canvas) -> None:
        super().__init__(config, canvas)
        self._quotes: list[dict[str, Any]] = []
        self._logos: dict[str, Image.Image | None] = {}
        self._logos_fetched: set[str] = set()

        # Pre-built marquee images (one per price display mode)
        self._marquee_pct: Image.Image | None = None
        self._marquee_dollar: Image.Image | None = None
        self._marquee_w: int = 0

        # Paginate image cache keyed by (show_pct, page)
        self._page_cache: dict[tuple[bool, int], Image.Image] = {}

        # Runtime state
        self._offset: int = 0
        self._show_pct: bool = True
        self._alt_counter: int = 0
        self._page: int = 0
        self._page_counter: int = 0

    async def on_activate(self) -> None:
        self._offset = self.canvas.width
        self._show_pct = True
        self._alt_counter = 0
        self._page = 0
        self._page_counter = 0
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

        async with httpx.AsyncClient(timeout=10.0) as client:
            quote_tasks = [self._fetch_quote(client, s) for s in symbols]

            # Only fetch logos for symbols not yet attempted
            new_syms = [s for s in symbols if s not in self._logos_fetched]
            logo_tasks = (
                [self._fetch_logo(client, s) for s in new_syms]
                if show_icons and new_syms
                else []
            )

            results = await asyncio.gather(
                asyncio.gather(*quote_tasks, return_exceptions=True),
                asyncio.gather(*logo_tasks, return_exceptions=True) if logo_tasks else asyncio.sleep(0),
            )

        quote_results = results[0]
        logo_results  = results[1] if logo_tasks else []

        quotes = [r for r in quote_results if isinstance(r, dict)]
        if quotes:
            self._quotes = quotes

        if isinstance(logo_results, (list, tuple)):
            for sym, logo in zip(new_syms, logo_results):
                self._logos[sym] = logo if isinstance(logo, Image.Image) else None
                self._logos_fetched.add(sym)

        self._page_cache.clear()
        self._build_images()

    async def _fetch_quote(
        self, client: httpx.AsyncClient, symbol: str
    ) -> dict[str, Any] | None:
        try:
            resp = await client.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                params={"range": "1d", "interval": "1d"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            data = resp.json()
            meta = data["chart"]["result"][0]["meta"]
            price: float = meta.get("regularMarketPrice", 0.0)
            prev: float = meta.get("previousClose") or meta.get("chartPreviousClose", price)
            change_pct = ((price - prev) / prev * 100) if prev else 0.0
            dollar_change = price - prev
            return {
                "symbol": symbol,
                "price": price,
                "change_pct": change_pct,
                "dollar_change": dollar_change,
            }
        except Exception:
            return None

    async def _fetch_logo(
        self, client: httpx.AsyncClient, symbol: str
    ) -> Image.Image | None:
        domain = TICKER_DOMAIN.get(symbol)
        if not domain:
            return None
        try:
            resp = await client.get(
                f"https://logo.clearbit.com/{domain}",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=5.0,
                follow_redirects=True,
            )
            if resp.status_code == 200:
                return Image.open(BytesIO(resp.content)).convert("RGBA")
        except Exception:
            pass
        return None

    # ── Layout ─────────────────────────────────────────────────────────────────

    def _compute_layout(self) -> dict[str, Any]:
        h = self.canvas.height
        display_mode = self.config.get("display_mode", "marquee")
        rows = max(1, int(self.config.get("rows", 1)))
        show_icons = bool(self.config.get("show_icons", True))

        if display_mode == "paginate":
            row_h = max(8, h // rows)
            n_rows = rows
        else:
            row_h = h
            n_rows = 1

        # Adaptive font and icon sizes based on row height
        if row_h >= 40:
            font_size, raw_icon = 16, 24
        elif row_h >= 28:
            font_size, raw_icon = 12, 16
        elif row_h >= 18:
            font_size, raw_icon = 10, 0
        else:
            font_size, raw_icon = 8, 0

        icon_size = raw_icon if (show_icons and raw_icon > 0) else 0

        return {
            "row_h": row_h,
            "n_rows": n_rows,
            "font_size": font_size,
            "icon_size": icon_size,
        }

    # ── Image building ─────────────────────────────────────────────────────────

    def _build_images(self) -> None:
        """Pre-build both price-display-mode marquee images and clear page cache."""
        if not self._quotes:
            return
        layout = self._compute_layout()
        self._marquee_pct    = self._render_marquee(layout, show_pct=True)
        self._marquee_dollar = self._render_marquee(layout, show_pct=False)
        self._marquee_w      = self._marquee_pct.width if self._marquee_pct else 0
        self._page_cache.clear()

    def _format_entry(self, q: dict[str, Any], show_pct: bool) -> tuple[str, str]:
        """Return (symbol_str, change_str) for a quote."""
        arrow  = _up_down_arrow(q["change_pct"])
        sign   = "+" if q["change_pct"] >= 0 else ""
        if show_pct:
            change = f"{sign}{q['change_pct']:.1f}% {arrow}"
        else:
            ds     = "+" if q["dollar_change"] >= 0 else ""
            change = f"${q['price']:.2f} {ds}{q['dollar_change']:.2f} {arrow}"
        return q["symbol"], change

    def _render_marquee(self, layout: dict, show_pct: bool) -> Image.Image | None:
        """Build the wide PIL image for horizontal scrolling."""
        if not self._quotes:
            return None

        font       = load_font(layout["font_size"])
        icon_size  = layout["icon_size"]
        h          = self.canvas.height
        gap        = max(3, h // 16)   # gap between icon and text
        spacer     = max(12, h // 4)   # gap between stock entries

        # Dummy draw for measurement
        dummy_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))

        # Pre-measure every element to compute total width
        entries: list[dict[str, Any]] = []
        total_w = 0
        for q in self._quotes:
            sym_str, chg_str = self._format_entry(q, show_pct)
            sym_w, sym_h  = _measure_text(dummy_draw, sym_str + " ", font)
            chg_w, chg_h  = _measure_text(dummy_draw, chg_str, font)
            text_h        = max(sym_h, chg_h)
            ascent        = dummy_draw.textbbox((0, 0), "Ay", font=font)[1]

            logo = self._logos.get(q["symbol"]) if icon_size > 0 else None
            icon_w = icon_size + gap if (logo is not None and icon_size > 0) else 0

            entry_w = icon_w + sym_w + chg_w + spacer
            entries.append({
                "q": q,
                "sym_str": sym_str + " ",
                "chg_str": chg_str,
                "sym_w": sym_w,
                "chg_w": chg_w,
                "text_h": text_h,
                "ascent": ascent,
                "logo": logo,
                "icon_w": icon_w,
                "entry_w": entry_w,
            })
            total_w += entry_w

        if total_w <= 0:
            return None

        img  = Image.new("RGB", (total_w, h), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        x    = 0

        for e in entries:
            q = e["q"]

            # Icon
            if e["logo"] is not None and icon_size > 0:
                icon_y = (h - icon_size) // 2
                resized = e["logo"].resize((icon_size, icon_size), Image.LANCZOS)
                _composite_icon(img, resized, x, icon_y)
                x += icon_size + gap

            # Text vertical centre
            text_y = _text_y_center(0, h, e["text_h"], e["ascent"])

            # Symbol (gray)
            draw.text((x, text_y), e["sym_str"], font=font, fill=_COLOR_SYM)
            x += e["sym_w"]

            # Change / price (colored)
            draw.text((x, text_y), e["chg_str"], font=font, fill=_quote_color(q["change_pct"]))
            x += e["chg_w"] + spacer

        return img

    def _build_page_image(self, layout: dict, show_pct: bool, page: int) -> Image.Image:
        """Build a canvas-sized image for one paginate page."""
        font      = load_font(layout["font_size"])
        row_h     = layout["row_h"]
        icon_size = layout["icon_size"]
        rows      = layout["n_rows"]
        gap       = max(3, row_h // 6)
        w, h      = self.canvas.width, self.canvas.height

        img  = Image.new("RGB", (w, h), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        dummy_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        ascent = dummy_draw.textbbox((0, 0), "Ay", font=font)[1]
        test_h = dummy_draw.textbbox((0, 0), "Ay", font=font)
        text_h = test_h[3] - test_h[1]

        start = page * rows
        visible = self._quotes[start : start + rows]

        for i, q in enumerate(visible):
            row_top = i * row_h
            x       = 2

            # Icon
            logo = self._logos.get(q["symbol"]) if icon_size > 0 else None
            if logo is not None:
                icon_y = row_top + (row_h - icon_size) // 2
                resized = logo.resize((icon_size, icon_size), Image.LANCZOS)
                _composite_icon(img, resized, x, icon_y)
                x += icon_size + gap

            sym_str, chg_str = self._format_entry(q, show_pct)
            text_y = _text_y_center(row_top, row_h, text_h, ascent)

            # Symbol
            sym_w = _measure_text(dummy_draw, sym_str, font)[0]
            draw.text((x, text_y), sym_str, font=font, fill=_COLOR_SYM)
            x += sym_w

            # Change / price — truncate to fit remaining canvas width
            draw.text((x, text_y), chg_str, font=font, fill=_quote_color(q["change_pct"]))

        return img

    # ── Rendering ──────────────────────────────────────────────────────────────

    async def render_frame(self) -> None:
        if not self._quotes:
            self._draw_loading()
            return

        price_interval = int(self.config.get("price_display_interval", 90))
        display_mode   = self.config.get("display_mode", "marquee")

        # Toggle price / % display mode
        self._alt_counter += 1
        if self._alt_counter >= price_interval:
            self._alt_counter = 0
            self._show_pct    = not self._show_pct

        if display_mode == "marquee":
            self._render_marquee_frame()
        else:
            self._render_paginate_frame()

    def _render_marquee_frame(self) -> None:
        img = self._marquee_pct if self._show_pct else self._marquee_dollar
        if img is None:
            self._build_images()
            img = self._marquee_pct if self._show_pct else self._marquee_dollar
        if img is None:
            return
        blit(self.canvas, img, self._offset)
        self._offset -= 2
        if self._offset < -self._marquee_w:
            self._offset = self.canvas.width

    def _render_paginate_frame(self) -> None:
        layout         = self._compute_layout()
        rows           = layout["n_rows"]
        frames_per_pge = int(self.config.get("frames_per_page", 90))
        max_pages      = max(1, (len(self._quotes) + rows - 1) // rows)

        self._page_counter += 1
        if self._page_counter >= frames_per_pge:
            self._page_counter = 0
            self._page         = (self._page + 1) % max_pages

        key = (self._show_pct, self._page)
        if key not in self._page_cache:
            self._page_cache[key] = self._build_page_image(layout, self._show_pct, self._page)

        blit(self.canvas, self._page_cache[key])

    def _draw_loading(self) -> None:
        font = load_font(12)
        msg  = "Fetching quotes..."
        dummy_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        bbox = dummy_draw.textbbox((0, 0), msg, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        img  = Image.new("RGB", (self.canvas.width, self.canvas.height))
        draw = ImageDraw.Draw(img)
        x = (self.canvas.width - tw) // 2
        y = (self.canvas.height - th) // 2 - bbox[1]
        draw.text((x, y), msg, font=font, fill=_COLOR_DIM)
        blit(self.canvas, img)
