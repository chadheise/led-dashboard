from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Any, ClassVar

import httpx
from PIL import Image, ImageDraw

from canvas.base import Canvas
from plugin_base import DisplayApp
from PIL import ImageFont

from apps._helpers import blit


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

# ── Colors ────────────────────────────────────────────────────────────────────

_COLOR_UP   = (80, 220, 80)
_COLOR_DOWN = (220, 80, 80)
_COLOR_SYM  = (200, 200, 200)
_COLOR_DIM  = (100, 100, 100)

# ── Pixel-perfect rendering primitives ────────────────────────────────────────

# Base bitmap font used for very small sizes (rendered 1-bit, fully binary).
_BASE_FONT: ImageFont.ImageFont = ImageFont.load_default()
_BASE_FONT_H: int = 10  # approximate cap height of the base font, pixels

# Grayscale threshold for FreeType → binary quantization.
# Pixels with coverage ≥ this value are "on"; below → "off".
# ~32 % coverage captures the full letterform without stray antialiasing dots.
_THRESHOLD: int = 80


def _quote_color(change_pct: float) -> tuple[int, int, int]:
    return _COLOR_UP if change_pct >= 0 else _COLOR_DOWN


def _bitmap_text_img(
    text: str,
    color: tuple[int, int, int],
    target_h: int,
    fixed_h: int | None = None,
) -> Image.Image:
    """Render text at *target_h* pixels tall with every pixel fully on or off.

    If *fixed_h* is given the output image is forced to exactly that height:
    shorter glyphs are embedded centred in a black canvas, taller ones are
    cropped from the centre.  Pass the cap-height of a representative "A" as
    fixed_h so that symbols like "$" (which have a taller glyph box) align
    with letters and every element in a row shares an identical image height.

    Two rendering strategies based on height:
    - Small (≤ base): 1-bit canvas → fully binary pixels, no antialiasing.
    - Larger: FreeType grayscale → threshold → binary with proper letterforms.
    """
    if not text:
        h = fixed_h if fixed_h else max(1, target_h)
        return Image.new("RGB", (1, h))

    if target_h <= _BASE_FONT_H:
        # ── 1-bit bitmap rendering ────────────────────────────────────────
        bbox = ImageDraw.Draw(Image.new("1", (1, 1))).textbbox(
            (0, 0), text, font=_BASE_FONT
        )
        gw = max(1, bbox[2] - bbox[0])
        gh = max(1, bbox[3] - bbox[1])
        mono = Image.new("1", (gw, gh), 0)
        ImageDraw.Draw(mono).text((-bbox[0], -bbox[1]), text, font=_BASE_FONT, fill=1)
        rgb = Image.new("RGB", (gw, gh), (0, 0, 0))
        rgb.putdata([(color if p else (0, 0, 0)) for p in mono.getdata()])
    else:
        # ── FreeType → grayscale → threshold ─────────────────────────────
        try:
            font = ImageFont.load_default(size=target_h)
        except TypeError:
            # Pillow < 10.1 fallback: scale base bitmap with NEAREST
            scale = max(1, round(target_h / _BASE_FONT_H))
            bbox = ImageDraw.Draw(Image.new("1", (1, 1))).textbbox(
                (0, 0), text, font=_BASE_FONT
            )
            gw = max(1, bbox[2] - bbox[0])
            gh = max(1, bbox[3] - bbox[1])
            mono = Image.new("1", (gw, gh), 0)
            ImageDraw.Draw(mono).text((-bbox[0], -bbox[1]), text, font=_BASE_FONT, fill=1)
            rgb = Image.new("RGB", (gw, gh), (0, 0, 0))
            rgb.putdata([(color if p else (0, 0, 0)) for p in mono.getdata()])
            rgb = rgb.resize((gw * scale, gh * scale), Image.NEAREST)
        else:
            bbox = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox(
                (0, 0), text, font=font
            )
            gw = max(1, bbox[2] - bbox[0])
            gh = max(1, bbox[3] - bbox[1])
            gray = Image.new("L", (gw, gh), 0)
            ImageDraw.Draw(gray).text((-bbox[0], -bbox[1]), text, font=font, fill=255)
            rgb = Image.new("RGB", (gw, gh), (0, 0, 0))
            rgb.putdata(
                [(color if p >= _THRESHOLD else (0, 0, 0)) for p in gray.getdata()]
            )

    # ── Force a fixed output height if requested ──────────────────────────
    if fixed_h is not None and rgb.height != fixed_h:
        if rgb.height > fixed_h:
            # Scale DOWN proportionally. NEAREST resampling samples one source
            # pixel per destination pixel so binary values are preserved — no
            # blending, no antialiasing introduced.
            new_w = max(1, round(rgb.width * fixed_h / rgb.height))
            rgb = rgb.resize((new_w, fixed_h), Image.NEAREST)
        else:
            # Glyph shorter than slot — embed centred in a black canvas.
            canvas = Image.new("RGB", (rgb.width, fixed_h), (0, 0, 0))
            canvas.paste(rgb, (0, (fixed_h - rgb.height) // 2))
            rgb = canvas

    return rgb


def _arrow_img(
    up: bool,
    size: int,
    color: tuple[int, int, int],
) -> Image.Image:
    """Draw a solid pixel-perfect triangle arrow of the given size.

    up=True  → ▲ (apex at top, base at bottom)
    up=False → ▼ (apex at bottom, base at top)
    """
    size = max(3, size)
    img  = Image.new("RGB", (size, size), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx   = size // 2
    if up:
        pts = [(cx, 0), (0, size - 1), (size - 1, size - 1)]
    else:
        pts = [(0, 0), (size - 1, 0), (cx, size - 1)]
    draw.polygon(pts, fill=color)
    return img


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
    global_config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Stock Ticker — Global Settings",
        "properties": {
            "finnhub_api_key": {
                "type": "string",
                "title": "Finnhub API Key",
                "default": "",
            },
        },
    }
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
            "scene_duration": {
                "type": "number",
                "title": "Scene duration (s)",
                "default": 60,
            },
        },
        "required": [],
    }

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def __init__(self, config: dict[str, Any], canvas: Canvas, global_config: dict[str, Any] | None = None) -> None:
        super().__init__(config, canvas, global_config)
        self._quotes: list[dict[str, Any]] = []
        self._logos: dict[str, Image.Image | None] = {}
        self._logos_fetched: set[str] = set()

        # Marquee: one image per row, two price modes.
        # Indexed [row_index]; both lists are always the same length.
        self._marquee_pct_rows: list[Image.Image | None] = []
        self._marquee_dol_rows: list[Image.Image | None] = []
        self._row_widths: list[int] = []
        self._row_offsets: list[float] = []   # fractional for smooth sub-pixel speeds
        self._row_speeds:  list[float] = []

        # Paginate image cache keyed by (show_pct, page)
        self._page_cache: dict[tuple[bool, int], Image.Image] = {}

        # Shared runtime state
        self._show_pct:    bool = True
        self._alt_counter: int  = 0
        self._page:        int  = 0
        self._page_counter:int  = 0

    async def on_activate(self) -> None:
        self._show_pct    = True
        self._alt_counter = 0
        self._page        = 0
        self._page_counter = 0
        self._row_offsets = []   # reset; _build_images will reinitialise
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
        h            = self.canvas.height
        display_mode = self.config.get("display_mode", "marquee")
        rows         = max(1, int(self.config.get("rows", 1)))
        show_icons   = bool(self.config.get("show_icons", True))

        # rows applies to both marquee and paginate
        row_h  = max(8, h // rows)
        n_rows = rows

        # Target text height in pixels: ~65 % of the available row height.
        # _bitmap_text_img() picks the right rendering strategy automatically:
        # 1-bit bitmap for small sizes, FreeType-then-threshold for larger ones.
        text_h = max(_BASE_FONT_H, round(row_h * 0.65))

        # Arrow drawn at the same height as the text so all elements are uniform.
        arrow_size = text_h

        # Icon slot matches text height; suppress for very small rows.
        icon_size = text_h if (show_icons and text_h >= 12) else 0

        return {
            "row_h":      row_h,
            "n_rows":     n_rows,
            "text_h":     text_h,
            "arrow_size": arrow_size,
            "icon_size":  icon_size,
        }

    # ── Image building ─────────────────────────────────────────────────────────

    def _build_images(self) -> None:
        """Pre-build marquee images for every row (both price modes) and clear page cache."""
        if not self._quotes:
            return
        layout  = self._compute_layout()
        n_rows  = layout["n_rows"]

        self._marquee_pct_rows, self._marquee_dol_rows = self._render_both_marquees(layout)
        self._row_widths = [img.width if img else 0 for img in self._marquee_pct_rows]

        # Preserve existing offsets if row count unchanged (avoids reset on data refresh)
        if len(self._row_offsets) != n_rows:
            cw = self.canvas.width
            self._row_offsets = [float(cw) for _ in range(n_rows)]

        # Scroll speeds: base 2 px/frame, rising to 3.5 px/frame for the last row
        if n_rows <= 1:
            self._row_speeds = [2.0]
        else:
            self._row_speeds = [
                2.0 + 1.5 * i / (n_rows - 1) for i in range(n_rows)
            ]

        self._page_cache.clear()

    def _format_change(self, q: dict[str, Any], show_pct: bool) -> str:
        """Return just the change string (no arrow, no +/-) for one mode."""
        if show_pct:
            return f"{abs(q['change_pct']):.1f}%"
        return f"${abs(q['dollar_change']):.2f}"

    def _render_both_marquees(
        self, layout: dict
    ) -> tuple[list[Image.Image | None], list[Image.Image | None]]:
        """Build marquee image pairs (pct + dollar) for every row.

        Stocks are distributed round-robin across rows so each row scrolls an
        independent subset.  Within a row both mode images share identical
        widths and element positions — switching between them replaces only the
        change value with no jump.
        """
        if not self._quotes:
            return [], []

        n_rows = layout["n_rows"]

        # Round-robin: quote i → row (i % n_rows)
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
        """Build the pct-mode and dollar-mode wide images for one marquee row.

        Both images are guaranteed to have the same total width so switching
        between them at any scroll offset is seamless.
        """
        if not quotes:
            return None, None

        text_h    = layout["text_h"]
        icon_size = layout["icon_size"]
        h         = layout["row_h"]   # each row image is row_h tall, not canvas height
        gap       = max(2, text_h // 5)
        spacer    = max(10, text_h * 2)

        # Use "A$%" so the $ fits at its natural height — shorter glyphs are
        # centred in padding, taller ones are scaled down, nothing is cropped.
        cap_h = _bitmap_text_img("A$%", _COLOR_SYM, text_h).height

        def vc(item_h: int) -> int:
            return max(0, (h - item_h) // 2)

        # Pre-render every element for both modes, fixing heights to cap_h
        entries: list[dict[str, Any]] = []
        total_w = 0
        for q in quotes:
            up    = q["change_pct"] >= 0
            color = _quote_color(q["change_pct"])

            sym_img = _bitmap_text_img(q["symbol"] + " ",             _COLOR_SYM, text_h, fixed_h=cap_h)
            prc_img = _bitmap_text_img(f"${q['price']:.2f} ",         color,       text_h, fixed_h=cap_h)
            arr_img = _arrow_img(up, max(3, round(cap_h * 2 / 3)), color)

            chg_pct_img = _bitmap_text_img(self._format_change(q, True),  color, text_h, fixed_h=cap_h)
            chg_dol_img = _bitmap_text_img(self._format_change(q, False), color, text_h, fixed_h=cap_h)
            chg_slot_w  = max(chg_pct_img.width, chg_dol_img.width)  # fixed slot width

            logo   = self._logos.get(q["symbol"]) if icon_size > 0 else None
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
            # Common elements drawn identically into both images
            for img in (img_pct, img_dol):
                ex = x
                if e["logo"] is not None and icon_size > 0:
                    resized = e["logo"].resize((icon_size, icon_size), Image.LANCZOS)
                    _composite_icon(img, resized, ex, vc(icon_size))
                    ex += icon_size + gap
                img.paste(e["sym_img"], (ex, vc(cap_h))); ex += e["sym_img"].width
                img.paste(e["prc_img"], (ex, vc(cap_h))); ex += e["prc_img"].width
                img.paste(e["arr_img"], (ex, vc(e["arr_img"].height))); ex += e["arr_img"].width + gap

            # Change value — left-aligned within the fixed-width slot
            chg_x = x + e["icon_w"] + e["sym_img"].width + e["prc_img"].width + e["arr_img"].width + gap
            img_pct.paste(e["chg_pct_img"], (chg_x, vc(cap_h)))
            img_dol.paste(e["chg_dol_img"], (chg_x, vc(cap_h)))

            x += e["icon_w"] + e["sym_img"].width + e["prc_img"].width + e["arr_img"].width + gap + e["chg_slot_w"] + spacer

        return img_pct, img_dol

    def _build_page_image(self, layout: dict, show_pct: bool, page: int) -> Image.Image:
        """Build a canvas-sized image for one paginate page."""
        text_h    = layout["text_h"]
        arr_sz    = layout["arrow_size"]
        icon_size = layout["icon_size"]
        row_h     = layout["row_h"]
        rows      = layout["n_rows"]
        gap       = max(2, text_h // 5)
        w, h      = self.canvas.width, self.canvas.height

        img   = Image.new("RGB", (w, h), (0, 0, 0))
        start = page * rows

        for i, q in enumerate(self._quotes[start : start + rows]):
            row_top = i * row_h
            x       = 2

            up      = q["change_pct"] >= 0
            color   = _quote_color(q["change_pct"])
            cap_h   = _bitmap_text_img("A$%", _COLOR_SYM, text_h).height
            sym_img = _bitmap_text_img(q["symbol"] + " ",              _COLOR_SYM, text_h, fixed_h=cap_h)
            prc_img = _bitmap_text_img(f"${q['price']:.2f} ",          color,       text_h, fixed_h=cap_h)
            chg_img = _bitmap_text_img(self._format_change(q, show_pct), color,    text_h, fixed_h=cap_h)
            arr_img = _arrow_img(up, max(3, round(cap_h * 2 / 3)), color)

            def vc(item_h: int) -> int:  # vertically centre in this row
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

            if x + chg_img.width <= w:   # clip if it doesn't fit
                img.paste(chg_img, (x, vc(cap_h)))

        return img

    # ── Rendering ──────────────────────────────────────────────────────────────

    async def render_frame(self) -> None:
        if not self._quotes:
            self._draw_loading()
            return

        price_interval = int(self.config.get("price_display_interval", 90))
        display_mode   = self.config.get("display_mode", "marquee")

        self._alt_counter += 1
        if self._alt_counter >= price_interval:
            self._alt_counter = 0
            self._show_pct    = not self._show_pct

        if display_mode == "marquee":
            self._render_marquee_frame()
        else:
            self._render_paginate_frame()

    def _blit_row(
        self, img: Image.Image, x_offset: int, y_start: int, row_h: int
    ) -> None:
        """Blit a marquee-row image into a horizontal band of the canvas."""
        data  = img.tobytes()
        iw, ih = img.size
        cw    = self.canvas.width
        ch    = self.canvas.height
        src_h = min(ih, row_h)

        dst_x_start = max(0, x_offset)
        dst_x_end   = min(cw, x_offset + iw)

        for dst_x in range(dst_x_start, dst_x_end):
            src_x = dst_x - x_offset
            for src_y in range(src_h):
                dst_y = y_start + src_y
                if dst_y >= ch:
                    break
                idx = (src_y * iw + src_x) * 3
                self.canvas.set_pixel(dst_x, dst_y,
                                      data[idx], data[idx + 1], data[idx + 2])

    def _render_marquee_frame(self) -> None:
        if not self._marquee_pct_rows:
            self._build_images()
        if not self._marquee_pct_rows:
            return

        rows_imgs = self._marquee_pct_rows if self._show_pct else self._marquee_dol_rows
        n_rows = len(rows_imgs)
        row_h  = self.canvas.height // n_rows

        for i, img in enumerate(rows_imgs):
            if img is None:
                continue
            row_y  = i * row_h
            offset = int(self._row_offsets[i])
            self._blit_row(img, offset, row_y, row_h)
            self._row_offsets[i] -= self._row_speeds[i]
            if self._row_offsets[i] < -self._row_widths[i]:
                self._row_offsets[i] = float(self.canvas.width)

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
        msg_img = _bitmap_text_img("Loading...", _COLOR_DIM, 1)
        img     = Image.new("RGB", (self.canvas.width, self.canvas.height))
        x       = (self.canvas.width  - msg_img.width)  // 2
        y       = (self.canvas.height - msg_img.height) // 2
        img.paste(msg_img, (x, y))
        blit(self.canvas, img)
