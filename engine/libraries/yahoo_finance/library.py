from __future__ import annotations

import asyncio
import csv
import json
import re
import time
from io import BytesIO, StringIO
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
_DOW30: list[str] = json.loads((_LIB_DIR / "dow30.json").read_text())
_NASDAQ100: list[str] = json.loads((_LIB_DIR / "nasdaq100.json").read_text())
_LOGO_TTL_SECONDS: float = 30 * 24 * 3600  # 30 days
_LIST_TTL_SECONDS: float = 24 * 3600        # 24 hours
_CHART_TTL_SECONDS: float = 3600            # 1 hour

_SP500_CSV_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies"
    "/main/data/constituents.csv"
)
_QUOTE_BATCH_SIZE = 100

_CHART_RANGE_PARAMS: dict[str, tuple[str, str]] = {
    "1W": ("5d", "15m"),
    "1M": ("1mo", "1d"),
    "3M": ("3mo", "1d"),
    "6M": ("6mo", "1wk"),
    "1Y": ("1y", "1wk"),
}

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
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">'
        '<path d="M18.86 1.56L14.27 11.87H19.4L24 1.56H18.86 '
        'M0 6.71L5.15 18.27L3.3 22.44H7.83L14.69 6.71H10.19L7.39 13.44L4.62 6.71H0 '
        'M15.62 12.87C13.95 12.87 12.71 14.12 12.71 15.58C12.71 17 13.91 18.19 15.5 18.19'
        'C17.18 18.19 18.43 16.96 18.43 15.5C18.43 14.03 17.23 12.87 15.62 12.87Z"/>'
        '</svg>'
    )
    global_config_schema: ClassVar[dict[str, Any]] = {}

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._logo_cache: dict[str, Image.Image | None] = {}
        data_dir = Path(__file__).parent.parent.parent / "data" / "yahoo_finance"
        self._logo_dir = data_dir / "logos"
        self._logo_dir.mkdir(parents=True, exist_ok=True)
        self._lists_dir = data_dir / "lists"
        self._lists_dir.mkdir(parents=True, exist_ok=True)
        self._charts_dir = data_dir / "charts"
        self._charts_dir.mkdir(parents=True, exist_ok=True)

    async def fetch_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            results = await asyncio.gather(
                *[self._fetch_quote(client, s) for s in symbols],
                return_exceptions=True,
            )
        return [r for r in results if isinstance(r, dict)]

    async def fetch_sp500_symbols(self) -> list[str]:
        cache_path = self._lists_dir / "sp500.json"
        if cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if age < _LIST_TTL_SECONDS:
                try:
                    return json.loads(cache_path.read_text())["symbols"]
                except Exception:
                    pass

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(_SP500_CSV_URL, headers={"User-Agent": "Mozilla/5.0"})
            reader = csv.DictReader(StringIO(resp.text))
            symbols = [row["Symbol"].strip().replace(".", "-") for row in reader if row.get("Symbol")]
            if symbols:
                cache_path.write_text(json.dumps({"symbols": symbols}))
                return symbols
        except Exception:
            pass

        # Fall back to hardcoded list on network failure
        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text())["symbols"]
            except Exception:
                pass
        return list(PRESET_GROUPS.get("largest_market_cap", []))

    def fetch_dow30_symbols(self) -> list[str]:
        return list(_DOW30)

    def fetch_nasdaq100_symbols(self) -> list[str]:
        return list(_NASDAQ100)

    async def fetch_largest_market_cap(self, n: int = 10) -> list[str]:
        cache_path = self._lists_dir / f"largest_market_cap_{n}.json"
        if cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if age < _LIST_TTL_SECONDS:
                try:
                    return json.loads(cache_path.read_text())["symbols"]
                except Exception:
                    pass

        universe = await self.fetch_sp500_symbols()
        batches = [
            universe[i : i + _QUOTE_BATCH_SIZE]
            for i in range(0, len(universe), _QUOTE_BATCH_SIZE)
        ]
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                raw_batches = await asyncio.gather(
                    *[self._fetch_market_caps(client, batch) for batch in batches],
                    return_exceptions=True,
                )
            cap_map: dict[str, float] = {}
            for result in raw_batches:
                if isinstance(result, dict):
                    cap_map.update(result)

            ranked = sorted(cap_map, key=lambda s: cap_map[s], reverse=True)[:n]
            if ranked:
                cache_path.write_text(json.dumps({"symbols": ranked}))
                return ranked
        except Exception:
            pass

        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text())["symbols"]
            except Exception:
                pass
        return list(PRESET_GROUPS.get("largest_market_cap", []))

    @staticmethod
    async def _fetch_market_caps(
        client: httpx.AsyncClient, symbols: list[str]
    ) -> dict[str, float]:
        try:
            resp = await client.get(
                "https://query1.finance.yahoo.com/v7/finance/quote",
                params={"symbols": ",".join(symbols), "fields": "marketCap"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            data = resp.json()
            results = data.get("quoteResponse", {}).get("result", [])
            return {
                r["symbol"]: float(r.get("marketCap", 0))
                for r in results
                if r.get("marketCap")
            }
        except Exception:
            return {}

    async def fetch_chart_data(self, symbol: str, time_frame: str) -> dict[str, Any] | None:
        cache_path = self._charts_dir / f"{symbol}_{time_frame}.json"
        if cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if age < _CHART_TTL_SECONDS:
                try:
                    return json.loads(cache_path.read_text())
                except Exception:
                    pass

        range_str, interval = _CHART_RANGE_PARAMS.get(time_frame, ("1mo", "1d"))
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                    params={"range": range_str, "interval": interval},
                    headers={"User-Agent": "Mozilla/5.0"},
                )
            data = resp.json()
            result = data["chart"]["result"][0]
            meta = result["meta"]
            timestamps: list[int] = result.get("timestamp", [])
            closes: list[float] = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            closes = [c for c in closes if c is not None]

            price: float = meta.get("regularMarketPrice", 0.0)
            # Use daily change fields directly; chartPreviousClose is the start of
            # the chart range and would give aggregate period change instead.
            change_pct: float = meta.get("regularMarketChangePercent", 0.0)
            dollar_change: float = meta.get("regularMarketChange", 0.0)
            if not change_pct and not dollar_change:
                prev: float = meta.get("previousClose") or meta.get("chartPreviousClose", price)
                change_pct = ((price - prev) / prev * 100) if prev else 0.0
                dollar_change = price - prev

            payload: dict[str, Any] = {
                "symbol": symbol,
                "timestamps": timestamps,
                "closes": closes,
                "current_price": price,
                "change_pct": change_pct,
                "dollar_change": dollar_change,
            }
            cache_path.write_text(json.dumps(payload))
            return payload
        except Exception:
            if cache_path.exists():
                try:
                    return json.loads(cache_path.read_text())
                except Exception:
                    pass
            return None

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
