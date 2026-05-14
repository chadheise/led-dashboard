from __future__ import annotations

import asyncio
import json
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Any, ClassVar

import httpx
from PIL import Image

from libraries.base import Library

try:
    import cairosvg as _cairosvg  # type: ignore[import-untyped]
    _CAIROSVG_AVAILABLE = True
except ImportError:
    _cairosvg = None  # type: ignore[assignment]
    _CAIROSVG_AVAILABLE = False


_LIB_DIR = Path(__file__).parent
_LOGO_TTL_SECONDS: float = 30 * 24 * 3600  # 30 days

# Loaded from JSON at import time so plugins can reference them as module-level names.
PRESET_GROUPS: dict[str, list[str]] = json.loads(
    (_LIB_DIR / "preset_groups.json").read_text()
)
INDEX_SYMBOLS: dict[str, list[str]] = json.loads(
    (_LIB_DIR / "index_symbols.json").read_text()
)
# ticker → [slug, hex_color]
_TICKER_SIMPLE_ICONS_RAW: dict[str, list[str]] = {
    k: v for k, v in json.loads((_LIB_DIR / "ticker_simple_icons.json").read_text()).items()
    if k != "comment"
}
TICKER_SIMPLE_ICONS: dict[str, tuple[str, str]] = {
    k: (v[0], v[1]) for k, v in _TICKER_SIMPLE_ICONS_RAW.items()
}
TICKER_DOMAIN: dict[str, str] = {
    k: v for k, v in json.loads((_LIB_DIR / "ticker_domain.json").read_text()).items()
    if k != "comment"
}


class YahooFinanceLibrary(Library):
    id: ClassVar[str] = "yahoo_finance"
    name: ClassVar[str] = "Yahoo Finance"
    description: ClassVar[str] = (
        "Real-time stock quotes and company logos via Yahoo Finance and Simple Icons"
    )
    icon: ClassVar[str] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="3,18 8,11 13,14 20,5"/><polyline points="16,5 20,5 20,9"/></svg>'
    )
    global_config_schema: ClassVar[dict[str, Any]] = {}

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._logo_cache: dict[str, Image.Image | None] = {}
        data_dir = Path(__file__).parent.parent.parent / "data" / "yahoo_finance"
        self._logo_dir = data_dir / "logos"
        self._logo_dir.mkdir(parents=True, exist_ok=True)

    async def fetch_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            results = await asyncio.gather(
                *[self._fetch_quote(client, s) for s in symbols],
                return_exceptions=True,
            )
        return [r for r in results if isinstance(r, dict)]

    async def fetch_logo(self, symbol: str) -> Image.Image | None:
        if symbol in self._logo_cache:
            return self._logo_cache[symbol]

        if symbol not in TICKER_SIMPLE_ICONS and symbol not in TICKER_DOMAIN:
            self._logo_cache[symbol] = None
            return None

        cache_path = self._logo_dir / f"{symbol}.png"
        now = time.time()

        if cache_path.exists():
            age = now - cache_path.stat().st_mtime
            if age < _LOGO_TTL_SECONDS:
                try:
                    img = Image.open(cache_path).convert("RGBA")
                    self._logo_cache[symbol] = img
                    return img
                except Exception:
                    pass

        downloaded = await self._download_logo(symbol)
        if downloaded is not None:
            try:
                downloaded.save(cache_path, format="PNG")
            except Exception:
                pass
            self._logo_cache[symbol] = downloaded
            return downloaded

        # Download failed — use stale disk file as fallback
        if cache_path.exists():
            try:
                img = Image.open(cache_path).convert("RGBA")
                self._logo_cache[symbol] = img
                return img
            except Exception:
                pass

        self._logo_cache[symbol] = None
        return None

    @staticmethod
    async def _download_logo(symbol: str) -> Image.Image | None:
        si = TICKER_SIMPLE_ICONS.get(symbol)
        if si:
            img = await YahooFinanceLibrary._fetch_simple_icon(si[0], si[1])
            if img is not None:
                return img

        domain = TICKER_DOMAIN.get(symbol)
        if domain:
            return await YahooFinanceLibrary._fetch_google_favicon(domain)

        return None

    @staticmethod
    async def _fetch_simple_icon(slug: str, hex_color: str) -> Image.Image | None:
        if not _CAIROSVG_AVAILABLE or _cairosvg is None:
            return None
        try:
            url = f"https://cdn.jsdelivr.net/npm/simple-icons/icons/{slug}.svg"
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return None
            svg = YahooFinanceLibrary._colorize_svg(resp.content, hex_color)
            png = _cairosvg.svg2png(bytestring=svg, output_width=64, output_height=64)
            return Image.open(BytesIO(png)).convert("RGBA")
        except Exception:
            return None

    @staticmethod
    def _colorize_svg(svg_bytes: bytes, hex_color: str) -> bytes:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        color = f"#{hex_color}" if luminance >= 0.20 else "#FFFFFF"
        svg = svg_bytes.decode("utf-8")
        svg = re.sub(r"(<svg\b[^>]*?)>", rf'\1 fill="{color}">', svg, count=1)
        return svg.encode("utf-8")

    @staticmethod
    async def _fetch_google_favicon(domain: str) -> Image.Image | None:
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                resp = await client.get(
                    "https://www.google.com/s2/favicons",
                    params={"domain": domain, "sz": "64"},
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code == 200:
                    return Image.open(BytesIO(resp.content)).convert("RGBA")
        except Exception:
            pass
        return None

    @staticmethod
    async def _fetch_quote(
        client: httpx.AsyncClient, symbol: str
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
            return {
                "symbol": symbol,
                "price": price,
                "change_pct": change_pct,
                "dollar_change": price - prev,
            }
        except Exception:
            return None
