from __future__ import annotations

import asyncio
import csv
import datetime
import json
import logging
import time
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import httpx
from PIL import Image

from libraries.base import Library

logger = logging.getLogger(__name__)

_AEROAPI_BASE = "https://aeroapi.flightaware.com/aeroapi"
_OPENSKY_ROUTES_URL = "https://opensky-network.org/api/routes"
_AIRPORTS_CSV_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"

_CACHE_PATH = Path("data/flightaware_cache.json")
_BUDGET_PATH = Path("data/flightaware_budget.json")
_ROUTES_CACHE_PATH = Path("data/opensky_routes_cache.json")
_AIRPORT_DB_PATH = Path("data/airports.csv")
_LOGO_CACHE_DIR = Path("data/logos")
_LOGO_META_PATH = Path("data/logo_meta.json")
_TRACKING_CACHE_PATH = Path("data/flightaware_tracking_cache.json")
_DEFAULT_LOGO_CACHE_TTL_DAYS: float = 30.0

# Module-level defaults — also used as schema defaults
_DEFAULT_CACHE_TTL_DAYS: int = 7
_DEFAULT_MONTHLY_BUDGET: int = 800  # ~$4 at $0.005/call
_COST_PER_CALL: float = 0.005  # AeroAPI free-tier rate, ~$0.005 per query
_ROUTES_CACHE_TTL_DAYS: float = 30.0  # Routes are very stable
_DEFAULT_TRACKING_CACHE_TTL_MINUTES: float = 10.0  # Schedule/status changes faster than routes

# ICAO 3-letter airline designator → IATA 2-letter code (for callsign prefix resolution)
_ICAO_PREFIX_TO_IATA: dict[str, str] = {
    "AAL": "AA",  # American Airlines
    "DAL": "DL",  # Delta Air Lines
    "UAL": "UA",  # United Airlines
    "SWA": "WN",  # Southwest Airlines
    "JBU": "B6",  # JetBlue Airways
    "ASA": "AS",  # Alaska Airlines
    "FFT": "F9",  # Frontier Airlines
    "NKS": "NK",  # Spirit Airlines
    "AAY": "G4",  # Allegiant Air
    "SCX": "SY",  # Sun Country Airlines
    "HAL": "HA",  # Hawaiian Airlines
    "SKW": "OO",  # SkyWest Airlines
    "RPA": "YX",  # Republic Airways
    "EGF": "MQ",  # American Eagle (Envoy Air)
    "PSA": "OH",  # PSA Airlines
    "ASH": "YV",  # Mesa Airlines
    "EDV": "9E",  # Endeavor Air
    "GJS": "G7",  # GoJet Airlines
    "PDT": "PT",  # Piedmont Airlines
    "AWI": "ZW",  # Air Wisconsin
    "ACA": "AC",  # Air Canada
    "WJA": "WS",  # WestJet
    "POE": "PD",  # Porter Airlines
    "TSC": "TS",  # Air Transat
    "AMX": "AM",  # Aeromexico
    "LAN": "LA",  # LATAM Airlines
    "AVA": "AV",  # Avianca
    "BAW": "BA",  # British Airways
    "DLH": "LH",  # Lufthansa
    "AFR": "AF",  # Air France
    "KLM": "KL",  # KLM
    "IBE": "IB",  # Iberia
    "VLG": "VY",  # Vueling
    "EZY": "U2",  # easyJet
    "RYR": "FR",  # Ryanair
    "WZZ": "W6",  # Wizz Air
    "SWR": "LX",  # Swiss International Air Lines
    "AUA": "OS",  # Austrian Airlines
    "BEL": "SN",  # Brussels Airlines
    "FIN": "AY",  # Finnair
    "SAS": "SK",  # SAS
    "NAX": "DY",  # Norwegian
    "LOT": "LO",  # LOT Polish Airlines
    "TAP": "TP",  # TAP Air Portugal
    "AEE": "A3",  # Aegean Airlines
    "PGT": "PC",  # Pegasus Airlines
    "THY": "TK",  # Turkish Airlines
    "UAE": "EK",  # Emirates
    "QTR": "QR",  # Qatar Airways
    "ETD": "EY",  # Etihad Airways
    "FDB": "FZ",  # flydubai
    "ABY": "G9",  # Air Arabia
    "OMA": "WY",  # Oman Air
    "GFA": "GF",  # Gulf Air
    "MEA": "ME",  # Middle East Airlines
    "RJA": "RJ",  # Royal Jordanian
    "MSR": "MS",  # EgyptAir
    "ETH": "ET",  # Ethiopian Airlines
    "SAA": "SA",  # South African Airways
    "SIA": "SQ",  # Singapore Airlines
    "CPA": "CX",  # Cathay Pacific
    "JAL": "JL",  # Japan Airlines
    "ANA": "NH",  # ANA (All Nippon Airways)
    "KAL": "KE",  # Korean Air
    "AAR": "OZ",  # Asiana Airlines
    "CCA": "CA",  # Air China
    "CES": "MU",  # China Eastern
    "CSN": "CZ",  # China Southern
    "IGO": "6E",  # IndiGo
    "SEJ": "SG",  # SpiceJet
    "AIC": "AI",  # Air India
    "QFA": "QF",  # Qantas
    "ANZ": "NZ",  # Air New Zealand
    "AFL": "SU",  # Aeroflot
    "SBI": "S7",  # Siberia Airlines (S7)
    "UTA": "UT",  # UTair
    "SDM": "FV",  # Rossiya Airlines
    "SVR": "U6",  # Ural Airlines
    "POB": "DP",  # Pobeda Airlines
    "AUI": "PS",  # Ukraine International Airlines
}

# Static airline IATA code → display name (covers the vast majority of commercial traffic)
_AIRLINE_NAMES: dict[str, str] = {
    "AA": "American Airlines",
    "DL": "Delta Air Lines",
    "UA": "United Airlines",
    "WN": "Southwest Airlines",
    "B6": "JetBlue Airways",
    "AS": "Alaska Airlines",
    "F9": "Frontier Airlines",
    "NK": "Spirit Airlines",
    "G4": "Allegiant Air",
    "SY": "Sun Country Airlines",
    "HA": "Hawaiian Airlines",
    "OO": "SkyWest Airlines",
    "YX": "Republic Airways",
    "MQ": "American Eagle",
    "OH": "PSA Airlines",
    "YV": "Mesa Airlines",
    "9E": "Endeavor Air",
    "G7": "GoJet Airlines",
    "PT": "Piedmont Airlines",
    "ZW": "Air Wisconsin",
    "AC": "Air Canada",
    "WS": "WestJet",
    "PD": "Porter Airlines",
    "TS": "Air Transat",
    "AM": "Aeromexico",
    "LA": "LATAM Airlines",
    "AV": "Avianca",
    "BA": "British Airways",
    "LH": "Lufthansa",
    "AF": "Air France",
    "KL": "KLM",
    "IB": "Iberia",
    "VY": "Vueling",
    "U2": "easyJet",
    "FR": "Ryanair",
    "W6": "Wizz Air",
    "LX": "Swiss",
    "OS": "Austrian Airlines",
    "SN": "Brussels Airlines",
    "AY": "Finnair",
    "SK": "SAS",
    "DY": "Norwegian",
    "LO": "LOT Polish Airlines",
    "TP": "TAP Air Portugal",
    "A3": "Aegean Airlines",
    "PC": "Pegasus Airlines",
    "TK": "Turkish Airlines",
    "EK": "Emirates",
    "QR": "Qatar Airways",
    "EY": "Etihad Airways",
    "FZ": "flydubai",
    "G9": "Air Arabia",
    "WY": "Oman Air",
    "GF": "Gulf Air",
    "ME": "Middle East Airlines",
    "RJ": "Royal Jordanian",
    "MS": "EgyptAir",
    "ET": "Ethiopian Airlines",
    "SA": "South African Airways",
    "SQ": "Singapore Airlines",
    "CX": "Cathay Pacific",
    "JL": "Japan Airlines",
    "NH": "ANA",
    "KE": "Korean Air",
    "OZ": "Asiana Airlines",
    "CA": "Air China",
    "MU": "China Eastern",
    "CZ": "China Southern",
    "6E": "IndiGo",
    "SG": "SpiceJet",
    "AI": "Air India",
    "QF": "Qantas",
    "NZ": "Air New Zealand",
    "SU": "Aeroflot",
    "S7": "Siberia Airlines",
    "UT": "UTair",
    "FV": "Rossiya",
    "U6": "Ural Airlines",
    "DP": "Pobeda",
    "PS": "Ukraine International Airlines",
}

# Common ICAO aircraft type codes → human-readable names
_AIRCRAFT_TYPE_NAMES: dict[str, str] = {
    "B735": "Boeing 737-500",
    "B736": "Boeing 737-600",
    "B737": "Boeing 737-700",
    "B738": "Boeing 737-800",
    "B739": "Boeing 737-900",
    "B37M": "Boeing 737 MAX 7",
    "B38M": "Boeing 737 MAX 8",
    "B39M": "Boeing 737 MAX 9",
    "B752": "Boeing 757-200",
    "B753": "Boeing 757-300",
    "B762": "Boeing 767-200",
    "B763": "Boeing 767-300",
    "B764": "Boeing 767-400",
    "B772": "Boeing 777-200",
    "B773": "Boeing 777-300",
    "B77L": "Boeing 777-200LR",
    "B77W": "Boeing 777-300ER",
    "B788": "Boeing 787-8",
    "B789": "Boeing 787-9",
    "B78X": "Boeing 787-10",
    "B744": "Boeing 747-400",
    "B748": "Boeing 747-8",
    "A318": "Airbus A318",
    "A319": "Airbus A319",
    "A320": "Airbus A320",
    "A321": "Airbus A321",
    "A19N": "Airbus A319neo",
    "A20N": "Airbus A320neo",
    "A21N": "Airbus A321neo",
    "A332": "Airbus A330-200",
    "A333": "Airbus A330-300",
    "A338": "Airbus A330-800neo",
    "A339": "Airbus A330-900neo",
    "A359": "Airbus A350-900",
    "A35K": "Airbus A350-1000",
    "A388": "Airbus A380-800",
    "E170": "Embraer E170",
    "E175": "Embraer E175",
    "E190": "Embraer E190",
    "E195": "Embraer E195",
    "E290": "Embraer E190-E2",
    "E295": "Embraer E195-E2",
    "CRJ2": "Bombardier CRJ-200",
    "CRJ7": "Bombardier CRJ-700",
    "CRJ9": "Bombardier CRJ-900",
    "CRJX": "Bombardier CRJ-1000",
    "DH8A": "Bombardier Dash 8-100",
    "DH8C": "Bombardier Dash 8-300",
    "DH8D": "Bombardier Dash 8-400",
    "AT72": "ATR 72-200",
    "AT75": "ATR 72-500",
    "AT76": "ATR 72-600",
    "MD11": "McDonnell Douglas MD-11",
    "MD83": "McDonnell Douglas MD-83",
    "SU95": "Sukhoi Superjet 100",
    "C208": "Cessna 208 Caravan",
    "C25B": "Cessna Citation CJ3",
    "C56X": "Cessna Citation Excel",
    "C680": "Cessna Citation Sovereign",
    "C750": "Cessna Citation X",
    "CL35": "Bombardier Challenger 350",
    "CL60": "Bombardier Challenger 600",
    "GLEX": "Bombardier Global Express",
    "GL5T": "Bombardier Global 5000",
    "GLF4": "Gulfstream IV",
    "GLF5": "Gulfstream V",
    "G450": "Gulfstream G450",
    "G550": "Gulfstream G550",
    "G650": "Gulfstream G650",
    "F900": "Dassault Falcon 900",
    "FA7X": "Dassault Falcon 7X",
    "F2TH": "Dassault Falcon 2000",
    "BE20": "Beechcraft King Air 200",
}


def _fmt_days(days: float) -> str:
    whole = int(days)
    if days == whole:
        return f"{whole} day" if whole == 1 else f"{whole} days"
    return f"{days:g} days"


def iata_from_callsign(callsign: str) -> str | None:
    """Return the IATA airline code for a callsign prefix, or None if unknown.

    Tries the 3-letter ICAO designator (e.g. UAL→UA, BAW→BA) first, then
    falls back to a 2-letter IATA prefix used directly in the callsign (e.g. DL699→DL).
    """
    if not callsign:
        return None
    cs = callsign.strip().upper()
    if len(cs) >= 3:
        iata = _ICAO_PREFIX_TO_IATA.get(cs[:3])
        if iata:
            return iata
    if len(cs) >= 2 and cs[:2] in _AIRLINE_NAMES:
        return cs[:2]
    return None


class FlightAwareLibrary(Library):
    id: ClassVar[str] = "flightaware"
    name: ClassVar[str] = "FlightAware AeroAPI"
    has_status: ClassVar[bool] = True
    description: ClassVar[str] = (
        "Flight enrichment (route, airline, aircraft type) and single-flight "
        "schedule/status tracking via FlightAware AeroAPI"
    )
    icon: ClassVar[str] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="10"/>'
        '<line x1="2" y1="12" x2="22" y2="12"/>'
        '<path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/></svg>'
    )
    global_config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "FlightAware AeroAPI",
        "properties": {
            "flightaware_api_key": {
                "type": "string",
                "title": "AeroAPI Key (optional)",
                "default": "",
                "x-no-reset": True,
            },
            "cache_ttl_days": {
                "type": "number",
                "title": "Enrichment cache TTL (days)",
                "description": (
                    "How long to cache flight route data before re-fetching. "
                    "Route/airline info rarely changes — longer values save more API calls. "
                    "Tip: 30 days is safe for most routes."
                ),
                "default": _DEFAULT_CACHE_TTL_DAYS,
                "minimum": 1,
                "maximum": 90,
            },
            "monthly_budget": {
                "type": "integer",
                "title": "Monthly API call budget",
                "description": (
                    "Maximum FlightAware API calls per month. "
                    "At ~$0.005/call on the free tier, $5 = 1000 calls. "
                    "Default 800 leaves a $1 safety margin. "
                    "Most routes are now resolved via free sources (OpenSky, static DB) "
                    "so this budget should last much longer."
                ),
                "default": _DEFAULT_MONTHLY_BUDGET,
                "minimum": 100,
                "maximum": 10000,
            },
            "logo_cache_ttl_days": {
                "type": "number",
                "title": "Airline logo cache TTL (days)",
                "description": (
                    "How long to cache downloaded airline logos before re-fetching. "
                    "Logos are stored on disk and rarely change — longer values reduce "
                    "network requests."
                ),
                "default": _DEFAULT_LOGO_CACHE_TTL_DAYS,
                "minimum": 1,
                "maximum": 365,
                "x-internal": True,
            },
            "tracking_cache_ttl_minutes": {
                "type": "number",
                "title": "Flight tracking cache TTL (minutes)",
                "description": (
                    "How long to cache single-flight schedule/status lookups (used by "
                    "Flight Tracker) before re-fetching. Shorter than the enrichment "
                    "cache since schedule/delay status changes much faster than routes."
                ),
                "default": _DEFAULT_TRACKING_CACHE_TTL_MINUTES,
                "minimum": 1,
                "maximum": 120,
            },
        },
    }

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        # callsign → (fetched_at_wall_time, enrichment_dict)
        self._enrichment_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._budget_month: str = ""
        self._budget_calls: int = 0
        # callsign → (fetched_at, route_dict) for OpenSky routes cache
        self._routes_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        # ICAO airport code → {iata, name}
        self._airport_db: dict[str, dict[str, str]] = {}
        self._airport_db_loaded: bool = False
        # iata → fetched_at wall time (tracks both hits and 404s)
        self._logo_meta: dict[str, float] = {}
        # "{ident}|{date or ''}" → (fetched_at, tracking_result)
        self._tracking_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._load_disk_cache()
        self._load_budget()
        self._load_routes_cache()
        self._load_logo_meta()
        self._load_tracking_cache()

    # ── Config properties ─────────────────────────────────────────────────────

    @property
    def _cache_ttl(self) -> float:
        """Cache TTL in seconds, read from config."""
        return float(self._config.get("cache_ttl_days", _DEFAULT_CACHE_TTL_DAYS)) * 24 * 3600

    @property
    def _budget_limit(self) -> int:
        """Monthly call budget, read from config."""
        return int(self._config.get("monthly_budget", _DEFAULT_MONTHLY_BUDGET))

    @property
    def _logo_cache_ttl(self) -> float:
        """Logo disk-cache TTL in seconds, read from config."""
        return float(self._config.get("logo_cache_ttl_days", _DEFAULT_LOGO_CACHE_TTL_DAYS)) * 24 * 3600

    @property
    def _tracking_cache_ttl(self) -> float:
        """Flight-tracking disk-cache TTL in seconds, read from config."""
        return float(
            self._config.get("tracking_cache_ttl_minutes", _DEFAULT_TRACKING_CACHE_TTL_MINUTES)
        ) * 60

    # ── Disk cache ────────────────────────────────────────────────────────────

    def _load_disk_cache(self) -> None:
        try:
            if _CACHE_PATH.exists():
                raw = json.loads(_CACHE_PATH.read_text())
                now = time.time()
                self._enrichment_cache = {
                    cs: (entry["fetched_at"], entry["data"])
                    for cs, entry in raw.items()
                    if now - entry["fetched_at"] < self._cache_ttl
                }
                logger.info(
                    "FlightAware: loaded %d cached enrichments from disk",
                    len(self._enrichment_cache),
                )
        except Exception as exc:
            logger.warning("FlightAware: cache load failed: %s", exc)

    def _save_disk_cache(self) -> None:
        try:
            _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            now = time.time()
            payload = {
                cs: {"fetched_at": ts, "data": d}
                for cs, (ts, d) in self._enrichment_cache.items()
                if now - ts < self._cache_ttl
            }
            tmp = _CACHE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.rename(_CACHE_PATH)
        except Exception as exc:
            logger.warning("FlightAware: cache save failed: %s", exc)

    # ── OpenSky routes cache ──────────────────────────────────────────────────

    def _load_routes_cache(self) -> None:
        try:
            if _ROUTES_CACHE_PATH.exists():
                raw = json.loads(_ROUTES_CACHE_PATH.read_text())
                ttl = _ROUTES_CACHE_TTL_DAYS * 24 * 3600
                now = time.time()
                self._routes_cache = {
                    cs: (entry["fetched_at"], entry["data"])
                    for cs, entry in raw.items()
                    if now - entry["fetched_at"] < ttl
                }
                logger.info(
                    "FlightAware: loaded %d cached OpenSky routes from disk",
                    len(self._routes_cache),
                )
        except Exception as exc:
            logger.warning("FlightAware: routes cache load failed: %s", exc)

    def _save_routes_cache(self) -> None:
        try:
            _ROUTES_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            ttl = _ROUTES_CACHE_TTL_DAYS * 24 * 3600
            now = time.time()
            payload = {
                cs: {"fetched_at": ts, "data": d}
                for cs, (ts, d) in self._routes_cache.items()
                if now - ts < ttl
            }
            tmp = _ROUTES_CACHE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.rename(_ROUTES_CACHE_PATH)
        except Exception as exc:
            logger.warning("FlightAware: routes cache save failed: %s", exc)

    # ── Logo disk cache ───────────────────────────────────────────────────────

    def _load_logo_meta(self) -> None:
        try:
            if _LOGO_META_PATH.exists():
                raw = json.loads(_LOGO_META_PATH.read_text())
                self._logo_meta = {k: float(v) for k, v in raw.items()}
                logger.info(
                    "FlightAware: loaded logo metadata for %d airlines", len(self._logo_meta)
                )
        except Exception as exc:
            logger.warning("FlightAware: logo meta load failed: %s", exc)

    def _save_logo_meta(self) -> None:
        try:
            _LOGO_META_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _LOGO_META_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._logo_meta))
            tmp.rename(_LOGO_META_PATH)
        except Exception as exc:
            logger.warning("FlightAware: logo meta save failed: %s", exc)

    # ── Flight-tracking cache ────────────────────────────────────────────────

    def _load_tracking_cache(self) -> None:
        try:
            if _TRACKING_CACHE_PATH.exists():
                raw = json.loads(_TRACKING_CACHE_PATH.read_text())
                now = time.time()
                self._tracking_cache = {
                    key: (entry["fetched_at"], entry["data"])
                    for key, entry in raw.items()
                    if now - entry["fetched_at"] < self._tracking_cache_ttl
                }
                logger.info(
                    "FlightAware: loaded %d cached tracking results from disk",
                    len(self._tracking_cache),
                )
        except Exception as exc:
            logger.warning("FlightAware: tracking cache load failed: %s", exc)

    def _save_tracking_cache(self) -> None:
        try:
            _TRACKING_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            now = time.time()
            payload = {
                key: {"fetched_at": ts, "data": d}
                for key, (ts, d) in self._tracking_cache.items()
                if now - ts < self._tracking_cache_ttl
            }
            tmp = _TRACKING_CACHE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.rename(_TRACKING_CACHE_PATH)
        except Exception as exc:
            logger.warning("FlightAware: tracking cache save failed: %s", exc)

    # ── Airport DB ────────────────────────────────────────────────────────────

    async def _ensure_airport_db(self) -> None:
        """Load airport DB from disk or download from OurAirports if missing."""
        if self._airport_db_loaded:
            return
        self._airport_db_loaded = True  # set early to prevent concurrent loads
        try:
            if not _AIRPORT_DB_PATH.exists():
                logger.info("FlightAware: downloading OurAirports airport DB…")
                async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                    resp = await client.get(_AIRPORTS_CSV_URL)
                if resp.status_code != 200:
                    logger.warning("FlightAware: airport DB download failed: HTTP %d", resp.status_code)
                    return
                _AIRPORT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                _AIRPORT_DB_PATH.write_bytes(resp.content)
                logger.info("FlightAware: airport DB downloaded (%d bytes)", len(resp.content))
            self._airport_db = _parse_airport_csv(_AIRPORT_DB_PATH.read_text(encoding="utf-8"))
            logger.info("FlightAware: airport DB loaded (%d entries)", len(self._airport_db))
        except Exception as exc:
            logger.warning("FlightAware: airport DB load failed: %s", exc)

    # ── Monthly budget ────────────────────────────────────────────────────────

    def _load_budget(self) -> None:
        current_month = datetime.date.today().strftime("%Y-%m")
        self._budget_month = current_month
        self._budget_calls = 0
        try:
            if _BUDGET_PATH.exists():
                data = json.loads(_BUDGET_PATH.read_text())
                if data.get("month") == current_month:
                    self._budget_calls = int(data.get("calls", 0))
                    logger.info(
                        "FlightAware: %d/%d API calls used this month",
                        self._budget_calls, self._budget_limit,
                    )
        except Exception as exc:
            logger.warning("FlightAware: budget load failed: %s", exc)

    @property
    def budget_tier(self) -> str:
        limit = self._budget_limit
        ratio = self._budget_calls / limit
        if ratio >= 1.0:
            return "disabled"
        if ratio >= 0.95:
            return "minimal"
        if ratio >= 0.80:
            return "conservative"
        return "normal"

    def _charge_budget(self, count: int) -> None:
        if count <= 0:
            return
        prev_tier = self.budget_tier
        self._budget_calls += count
        new_tier = self.budget_tier
        if new_tier != prev_tier:
            logger.warning(
                "FlightAware: budget tier changed %s → %s (%d/%d calls this month)",
                prev_tier, new_tier, self._budget_calls, self._budget_limit,
            )
        try:
            _BUDGET_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _BUDGET_PATH.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"month": self._budget_month, "calls": self._budget_calls})
            )
            tmp.rename(_BUDGET_PATH)
        except Exception as exc:
            logger.warning("FlightAware: budget save failed: %s", exc)

    # ── Status (settings UI) ──────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Budget cost + enrichment-cache summary for the settings UI."""
        self._load_budget()
        self._load_disk_cache()
        self._load_routes_cache()

        calls = self._budget_calls
        limit = self._budget_limit
        cost_used = calls * _COST_PER_CALL
        cost_limit = limit * _COST_PER_CALL

        entries = len(self._enrichment_cache)
        last_updated = max(
            (ts for ts, _ in self._enrichment_cache.values()), default=None
        )
        ttl_days = float(self._config.get("cache_ttl_days", _DEFAULT_CACHE_TTL_DAYS))

        routes_entries = len(self._routes_cache)
        airport_db_size = (
            f"{len(self._airport_db):,} airports" if self._airport_db
            else ("loaded" if _AIRPORT_DB_PATH.exists() else "not downloaded yet")
        )

        return {
            "sections": [
                {
                    "label": "Monthly budget",
                    "items": [
                        {"label": "API calls used", "value": f"{calls:,} / {limit:,}"},
                        {
                            "label": "Estimated cost",
                            "value": f"${cost_used:.2f} / ${cost_limit:.2f}",
                        },
                        {"label": "Budget tier", "value": self.budget_tier},
                        {"label": "Billing month", "value": self._budget_month},
                    ],
                },
                {
                    "label": "Enrichment cache",
                    "items": [
                        {"label": "Cached flights", "value": f"{entries:,}"},
                        {
                            "label": "Last cache update",
                            "value": last_updated,
                            "kind": "timestamp",
                        },
                        {"label": "Cache duration", "value": _fmt_days(ttl_days)},
                    ],
                },
                {
                    "label": "Free data sources",
                    "items": [
                        {"label": "OpenSky routes cached", "value": f"{routes_entries:,}"},
                        {"label": "Airport DB", "value": airport_db_size},
                    ],
                },
            ],
        }

    # ── Public API ────────────────────────────────────────────────────────────

    async def enrich_flights(
        self,
        callsigns: list[str],
        icao24_map: dict[str, str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Enrich a list of callsigns with route/airline/aircraft data.

        Waterfall (cheapest first):
          1. Existing enrichment cache (no network)
          2. OpenSky routes API + static airport/airline/type lookups (free)
          3. FlightAware AeroAPI (budget-limited, paid fallback)
        """
        if not callsigns:
            return {}

        icao24_map = icao24_map or {}
        now = time.time()
        result: dict[str, dict[str, Any]] = {}
        cache_misses: list[str] = []

        # Step 1: serve from enrichment cache
        for cs in callsigns:
            entry = self._enrichment_cache.get(cs)
            if entry is not None and (now - entry[0]) < self._cache_ttl:
                result[cs] = entry[1]
            else:
                cache_misses.append(cs)

        if not cache_misses:
            logger.debug("FlightAware: all %d flights served from cache", len(result))
            return result

        logger.info(
            "FlightAware: %d cache hits, %d misses → trying free sources",
            len(result), len(cache_misses),
        )

        # Step 2: free sources — OpenSky routes + static lookups
        await self._ensure_airport_db()
        free_results = await self._enrich_from_free_sources(cache_misses, icao24_map)
        still_missing: list[str] = []

        for cs in cache_misses:
            partial = free_results.get(cs)
            if partial and partial.get("origin") and partial.get("dest"):
                # Good enough — store in enrichment cache so we won't re-check
                self._enrichment_cache[cs] = (now, partial)
                result[cs] = partial
                logger.debug("FlightAware: %s enriched from free sources", cs)
            else:
                # Merge whatever partial data we have, still need FlightAware
                still_missing.append(cs)

        if free_results:
            self._save_disk_cache()

        if not still_missing:
            logger.info("FlightAware: all misses resolved from free sources, 0 API calls used")
            return result

        # Step 3: FlightAware API (budget-gated)
        api_key = self._config.get("flightaware_api_key", "").strip()
        if not api_key:
            logger.debug("FlightAware: no API key configured, skipping paid enrichment")
            return result

        if self.budget_tier == "disabled":
            logger.warning("FlightAware: monthly budget exhausted, serving cache only")
            return result

        logger.info(
            "FlightAware: %d callsigns still need paid API enrichment (tier=%s)",
            len(still_missing), self.budget_tier,
        )

        async with httpx.AsyncClient(
            timeout=10.0,
            headers={"x-apikey": api_key},
        ) as client:
            responses = await asyncio.gather(
                *[self._fetch_enrichment(client, cs) for cs in still_missing],
                return_exceptions=True,
            )

        self._charge_budget(len(still_missing))

        disk_dirty = False
        for callsign, response in zip(still_missing, responses):
            if isinstance(response, dict):
                # Merge: free-source partial data may have some fields; FA fills the rest
                merged = {**(free_results.get(callsign) or {}), **response}
                self._enrichment_cache[callsign] = (now, merged)
                result[callsign] = merged
                disk_dirty = True

        if disk_dirty:
            self._save_disk_cache()

        logger.info("FlightAware: enriched %d/%d flights", len(result), len(callsigns))
        return result

    # ── Free-source enrichment ────────────────────────────────────────────────

    async def _enrich_from_free_sources(
        self,
        callsigns: list[str],
        icao24_map: dict[str, str],
    ) -> dict[str, dict[str, Any]]:
        """Try to build enrichment from OpenSky routes API + static lookups."""
        routes_ttl = _ROUTES_CACHE_TTL_DAYS * 24 * 3600
        now = time.time()

        to_fetch_routes: list[str] = []
        for cs in callsigns:
            entry = self._routes_cache.get(cs)
            if entry is None or (now - entry[0]) >= routes_ttl:
                to_fetch_routes.append(cs)

        if to_fetch_routes:
            async with httpx.AsyncClient(timeout=8.0) as client:
                route_responses = await asyncio.gather(
                    *[self._fetch_opensky_route(client, cs) for cs in to_fetch_routes],
                    return_exceptions=True,
                )
            routes_dirty = False
            for cs, resp in zip(to_fetch_routes, route_responses):
                if isinstance(resp, dict):
                    self._routes_cache[cs] = (now, resp)
                    routes_dirty = True
                else:
                    # Cache a negative result so we don't re-try on every cycle
                    self._routes_cache[cs] = (now, {})
                    routes_dirty = True
            if routes_dirty:
                self._save_routes_cache()

        result: dict[str, dict[str, Any]] = {}
        for cs in callsigns:
            cache_entry = self._routes_cache.get(cs)
            route_data = cache_entry[1] if cache_entry else {}
            enrichment = _build_enrichment_from_route(
                route_data, icao24_map.get(cs, ""), self._airport_db
            )
            if any(enrichment.values()):
                result[cs] = enrichment

        return result

    @staticmethod
    async def _fetch_opensky_route(
        client: httpx.AsyncClient, callsign: str
    ) -> dict[str, Any] | None:
        try:
            resp = await client.get(
                _OPENSKY_ROUTES_URL, params={"callsign": callsign}
            )
            if resp.status_code == 404:
                logger.debug("OpenSky routes: no route for %s", callsign)
                return None
            if resp.status_code != 200:
                logger.debug("OpenSky routes: HTTP %d for %s", resp.status_code, callsign)
                return None
            data = resp.json()
            route = data.get("route") or []
            return {
                "icao_origin": route[0] if len(route) > 0 else "",
                "icao_dest": route[1] if len(route) > 1 else "",
                "operator_iata": (data.get("operatorIata") or "").upper(),
            }
        except Exception as exc:
            logger.debug("OpenSky routes fetch failed for %s: %s", callsign, exc)
            return None

    async def fetch_logo(self, iata: str) -> Image.Image | None:
        logo_path = _LOGO_CACHE_DIR / f"{iata}.png"
        ttl = self._logo_cache_ttl
        now = time.time()

        fetched_at = self._logo_meta.get(iata)
        if fetched_at is not None and (now - fetched_at) < ttl:
            if logo_path.exists():
                try:
                    return Image.open(logo_path).convert("RGBA")
                except Exception as exc:
                    logger.warning("Logo disk read failed for %s: %s", iata, exc)
            else:
                return None  # cached 404

        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                resp = await client.get(
                    f"https://www.gstatic.com/flights/airline_logos/70px/{iata}.png"
                )
                if resp.status_code == 200:
                    img = Image.open(BytesIO(resp.content)).convert("RGBA")
                    try:
                        _LOGO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                        img.save(logo_path, "PNG")
                    except Exception as exc:
                        logger.warning("Logo disk save failed for %s: %s", iata, exc)
                    self._logo_meta[iata] = now
                    self._save_logo_meta()
                    logger.info("Logo fetched for %s", iata)
                    return img
                # Cache negative result to avoid repeated failed fetches
                self._logo_meta[iata] = now
                self._save_logo_meta()
                logger.debug("No logo for %s: HTTP %d", iata, resp.status_code)
        except Exception as exc:
            logger.debug("Logo fetch failed for %s: %s", iata, exc)
        return None

    @staticmethod
    async def _fetch_enrichment(
        client: httpx.AsyncClient, callsign: str
    ) -> dict[str, Any] | None:
        try:
            resp = await client.get(f"{_AEROAPI_BASE}/flights/{callsign}")
            if resp.status_code != 200:
                logger.warning(
                    "FlightAware %s: HTTP %d — %s",
                    callsign, resp.status_code, resp.text[:300],
                )
                return None
            data = resp.json()
            flights_list = data.get("flights", [])
            if not flights_list:
                logger.debug("FlightAware %s: no flights in response", callsign)
                return None
            flight = flights_list[0]
            fields = _extract_route_fields(flight)

            logger.info(
                "FlightAware %s: %s→%s %s(%s) %s",
                callsign, fields["origin"], fields["dest"],
                fields["airline"], fields["operator_iata"], fields["aircraft_type"],
            )
            return fields
        except Exception as exc:
            logger.warning("FlightAware enrichment failed for %s: %s", callsign, exc)
            return None

    # ── Flight tracking (Flight Tracker app) ───────────────────────────────────

    async def track_flight(
        self, ident: str, date: str | None = None, tz: str | None = None
    ) -> dict[str, Any] | None:
        """Return schedule/status/live-position info for one flight, or None.

        ``ident`` is an airline + flight number (e.g. ``"DL699"``); ``date`` is an
        optional ``YYYY-MM-DD`` string selecting which instance of a recurring
        flight number to track (soonest non-cancelled instance if omitted).
        ``tz`` is the user's IANA timezone, used to interpret ``date`` against
        each flight's UTC departure time so evening flights aren't missed by an
        off-by-one date.

        Budget-gated like ``enrich_flights`` (shares the same monthly budget —
        no separate pool). Callers are expected to only invoke this when the
        flight is within its useful tracking window (about to depart, airborne,
        or recently landed); this method itself just fetches-or-serves-cache.
        """
        key = f"{ident}|{date or ''}|{tz or ''}"
        now = time.time()
        cached = self._tracking_cache.get(key)

        api_key = self._config.get("flightaware_api_key", "").strip()
        if not api_key or self.budget_tier == "disabled":
            return cached[1] if cached else None

        if cached is not None and (now - cached[0]) < self._tracking_cache_ttl:
            return cached[1]

        try:
            async with httpx.AsyncClient(
                timeout=10.0, headers={"x-apikey": api_key}
            ) as client:
                resp = await client.get(f"{_AEROAPI_BASE}/flights/{ident}")
            if resp.status_code != 200:
                logger.warning(
                    "FlightAware tracking %s: HTTP %d — %s",
                    ident, resp.status_code, resp.text[:300],
                )
                return cached[1] if cached else None
            data = resp.json()
        except Exception as exc:
            logger.warning("FlightAware tracking failed for %s: %s", ident, exc)
            return cached[1] if cached else None

        self._charge_budget(1)

        instance = _select_flight_instance(data.get("flights", []), date, tz)
        if instance is None:
            result: dict[str, Any] = {"found": False, "ident": ident}
        else:
            result = {"found": True, "ident": ident, **_extract_tracking_fields(instance)}

        self._tracking_cache[key] = (now, result)
        self._save_tracking_cache()
        logger.info("FlightAware tracking %s: found=%s", ident, result["found"])
        return result


# ── Module-level helpers ──────────────────────────────────────────────────────

def _extract_route_fields(flight: dict[str, Any]) -> dict[str, Any]:
    """Extract origin/dest/airline/aircraft-type fields from an AeroAPI flight object.

    Shared by ``_fetch_enrichment`` (route enrichment) and flight tracking
    (``_extract_tracking_fields``) — both consume the same ``/flights/{ident}``
    response shape.
    """
    origin_obj = flight.get("origin") or {}
    dest_obj = flight.get("destination") or {}
    origin = origin_obj.get("code_iata") or origin_obj.get("code", "")
    dest = dest_obj.get("code_iata") or dest_obj.get("code", "")
    origin_name = origin_obj.get("name", "")
    dest_name = dest_obj.get("name", "")
    airline = flight.get("operator") or ""
    operator_iata = flight.get("operator_iata") or ""
    aircraft_type = flight.get("aircraft_type", "")

    return {
        "origin": origin.upper() if origin else "",
        "dest": dest.upper() if dest else "",
        "origin_name": origin_name,
        "dest_name": dest_name,
        "airline": airline,
        "operator_iata": operator_iata.upper(),
        "aircraft_type": aircraft_type,
    }


def _local_date(iso_utc: str, tz: str | None) -> str | None:
    """The ``YYYY-MM-DD`` date of a UTC ISO timestamp, in timezone ``tz``.

    Falls back to the UTC date when ``tz`` is missing or invalid.
    """
    if not iso_utc:
        return None
    try:
        dt = datetime.datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    if tz:
        try:
            dt = dt.astimezone(ZoneInfo(tz))
        except Exception:
            pass
    return dt.date().isoformat()


def _select_flight_instance(
    flights: list[dict[str, Any]], date: str | None, tz: str | None = None
) -> dict[str, Any] | None:
    """Pick which instance of a (possibly recurring) flight number to track.

    With no date, picks the soonest non-cancelled instance. With a date
    (``YYYY-MM-DD``), matches the instance whose departure date — interpreted in
    the user's timezone ``tz`` — equals it. If the timezone is unknown (so the
    true local date can't be computed) it falls back to the nearest instance
    within ±1 day, rather than falsely reporting the flight as not found.
    """
    if not flights:
        return None

    if date is None:
        candidates = [f for f in flights if not f.get("cancelled")]
        candidates.sort(key=lambda f: f.get("scheduled_off") or "")
        return candidates[0] if candidates else None

    # Exact match on the flight's local departure date.
    for flight in flights:
        if _local_date(flight.get("scheduled_off") or "", tz) == date:
            return flight

    # Fallback: nearest non-cancelled instance within ±1 day of the request.
    try:
        target = datetime.datetime.strptime(date, "%Y-%m-%d").date()
    except Exception:
        return None
    best: dict[str, Any] | None = None
    best_delta: int | None = None
    for flight in flights:
        if flight.get("cancelled"):
            continue
        local = _local_date(flight.get("scheduled_off") or "", tz)
        if not local:
            continue
        try:
            cand = datetime.datetime.strptime(local, "%Y-%m-%d").date()
        except Exception:
            continue
        delta = abs((cand - target).days)
        if delta <= 1 and (best_delta is None or delta < best_delta):
            best, best_delta = flight, delta
    return best


def _extract_tracking_fields(flight: dict[str, Any]) -> dict[str, Any]:
    """Extract schedule/status/delay/live-position fields for flight tracking."""
    fields = _extract_route_fields(flight)

    last_position = flight.get("last_position") or {}
    live: dict[str, Any] | None = None
    if last_position:
        altitude = last_position.get("altitude")
        live = {
            "lat": last_position.get("latitude"),
            "lon": last_position.get("longitude"),
            "alt_ft": altitude * 100 if altitude is not None else None,
            "gs_kt": last_position.get("groundspeed"),
            "heading": last_position.get("heading"),
            "updated_at": last_position.get("timestamp"),
        }

    fields.update({
        "status": flight.get("status", ""),
        "scheduled_off": flight.get("scheduled_off"),
        "estimated_off": flight.get("estimated_off"),
        "actual_off": flight.get("actual_off"),
        "scheduled_on": flight.get("scheduled_on"),
        "estimated_on": flight.get("estimated_on"),
        "actual_on": flight.get("actual_on"),
        "departure_delay": flight.get("departure_delay"),
        "arrival_delay": flight.get("arrival_delay"),
        "progress_percent": flight.get("progress_percent"),
        "live": live,
        "icao24": (last_position.get("icao24") or "").lower(),
    })
    return fields


def _parse_airport_csv(text: str) -> dict[str, dict[str, str]]:
    """Parse OurAirports airports.csv into ICAO→{iata, name}."""
    db: dict[str, dict[str, str]] = {}
    try:
        reader = csv.DictReader(StringIO(text))
        for row in reader:
            icao = (row.get("ident") or "").strip().upper()
            iata = (row.get("iata_code") or "").strip().upper()
            name = (row.get("name") or "").strip()
            if icao and iata:
                db[icao] = {"iata": iata, "name": name}
    except Exception as exc:
        logger.warning("FlightAware: airport CSV parse error: %s", exc)
    return db


def _build_enrichment_from_route(
    route_data: dict[str, Any],
    icao24: str,
    airport_db: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Build an enrichment dict from OpenSky route data + static lookups."""
    if not route_data:
        return {}

    operator_iata = route_data.get("operator_iata", "").upper()
    airline = _AIRLINE_NAMES.get(operator_iata, "")

    icao_origin = (route_data.get("icao_origin") or "").upper()
    icao_dest = (route_data.get("icao_dest") or "").upper()

    origin_info = airport_db.get(icao_origin, {})
    dest_info = airport_db.get(icao_dest, {})

    origin_iata = origin_info.get("iata", "")
    dest_iata = dest_info.get("iata", "")
    origin_name = origin_info.get("name", "")
    dest_name = dest_info.get("name", "")

    # Fall back to ICAO code if no IATA mapping found
    if not origin_iata and icao_origin:
        origin_iata = icao_origin
    if not dest_iata and icao_dest:
        dest_iata = icao_dest

    # Aircraft type from static ICAO type table (icao24 alone isn't enough without aircraft DB)
    aircraft_type = ""

    return {
        "origin": origin_iata,
        "dest": dest_iata,
        "origin_name": origin_name,
        "dest_name": dest_name,
        "airline": airline,
        "operator_iata": operator_iata,
        "aircraft_type": aircraft_type,
    }
