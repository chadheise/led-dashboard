from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Any, ClassVar

import httpx
from PIL import Image

from libraries.base import Library


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

    async def fetch_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            results = await asyncio.gather(
                *[self._fetch_quote(client, s) for s in symbols],
                return_exceptions=True,
            )
        return [r for r in results if isinstance(r, dict)]

    async def fetch_logo(self, symbol: str) -> Image.Image | None:
        domain = TICKER_DOMAIN.get(symbol)
        if not domain:
            return None
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                resp = await client.get(
                    f"https://logo.clearbit.com/{domain}",
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
