from __future__ import annotations

import asyncio
import time
from io import BytesIO
from pathlib import Path
from typing import Any, ClassVar

import httpx
from PIL import Image

from libraries.base import Library


_LOGO_TTL_SECONDS: float = 30 * 24 * 3600  # 30 days


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


class YahooFinanceLibrary(Library):
    id: ClassVar[str] = "yahoo_finance"
    name: ClassVar[str] = "Yahoo Finance"
    description: ClassVar[str] = "Real-time stock quotes and company logos via Yahoo Finance and Clearbit"
    icon: ClassVar[str] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="3,18 8,11 13,14 20,5"/><polyline points="16,5 20,5 20,9"/></svg>'
    )
    global_config_schema: ClassVar[dict[str, Any]] = {}

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._logo_cache: dict[str, Image.Image | None] = {}
        data_dir = Path(__file__).parent.parent.parent / "data"
        self._logo_dir = data_dir / "logos" / "stocks"
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

        domain = TICKER_DOMAIN.get(symbol)
        if not domain:
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

        downloaded = await self._download_logo(domain)
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
    async def _download_logo(domain: str) -> Image.Image | None:
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
