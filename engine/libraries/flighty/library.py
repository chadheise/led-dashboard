"""Flighty integration — the user's own and friends' flights via Flighty's app API.

Flighty (https://flighty.com) has no public API and no username/password; identity
is an anonymous, non-expiring bearer token minted for the app install. This library
talks to the same private endpoint the iOS/macOS app uses,
``POST https://api.flightyapp.com/v1/sync/full``, which returns a protobuf
delta-sync of every flight the account can see — the user's own flights **and**
connected friends' flights, each tagged with an owner UUID. See
``sync_parser.py`` for the reverse-engineered message format and
``README.md`` for how to obtain the tokens.

The library keeps a small on-disk store (the sync cursor + accumulated flight and
reference records) so each refresh is an incremental delta, and exposes
``fetch_flights()`` returning records already shaped like the Flight Tracker's
``_tracked`` dict (schedule/status/gate/terminal/baggage + an ``owner`` field).
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

import httpx

from libraries.base import Library
from libraries.flighty.sync_parser import parse_sync_response

logger = logging.getLogger(__name__)

_STATE_PATH = Path("data/flighty_state.json")
_DEFAULT_API_BASE = "https://api.flightyapp.com"
_DEFAULT_CACHE_TTL_MINUTES = 10.0
# Sync schema version + the entity keys the app sends in its cursor. On first run
# we request the account's own data from 0 (all flights + friends + connections)
# but mark the bulk/global reference tables (airports, airlines, aircraft types)
# as already-current — requesting those from 0 makes the server try to dump the
# entire global reference DB, which returns an empty page then HTTP 500. Airline
# and airport codes still resolve from objects embedded in the flight records, so
# skipping the reference dump costs nothing. After the first sync we echo the
# server's next cursor.
_SCHEMA_VERSION = "V_2026_07_10"
# Requested in full (timestamp 0) — the account's own records:
_CURSOR_FULL = (
    "flight", "connection", "connection_steps", "ticketInfo",
    "profile", "connected-friends", "userDetails",
)
# Marked current (skipped) — global reference + settings that must not be dumped:
_CURSOR_SKIP = (
    "user", "usersubscription", "airport", "cfv2", "airline", "pushsetting",
    "metro", "hdyhau", "connected-friends-push", "laSettings", "custom",
    "aircraft_type",
)
# Only flights whose scheduled departure is within this past window are considered
# "recent enough" to still show (matches the tracker's active-window behaviour).
_PAST_WINDOW_S = 6 * 3600


def _iso(epoch: int | None) -> str | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _account_uuid(auth_token: str) -> str:
    """The account (owner) UUID = the ``sub`` claim of the bearer JWT."""
    try:
        payload = auth_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return str(data.get("sub", ""))
    except (IndexError, ValueError, binascii.Error, json.JSONDecodeError):
        return ""


class FlightyLibrary(Library):
    id: ClassVar[str] = "flighty"
    name: ClassVar[str] = "Flighty"
    has_status: ClassVar[bool] = True
    description: ClassVar[str] = (
        "Imports upcoming flights (your own and connected friends') from the "
        "Flighty app, including gate, terminal, delay and baggage detail. "
        "Requires a one-time token capture — see the Flighty library README."
    )
    icon: ClassVar[str] = (Path(__file__).parent / "icon.svg").read_text()
    global_config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Flighty",
        "properties": {
            "auth_token": {
                "type": "string",
                "title": "Authorization token",
                "description": (
                    "How to get it: run an HTTPS-inspecting proxy (e.g. Proxyman, "
                    "mitmproxy or Charles) in front of a device running the Flighty "
                    "app, open Flighty and let it sync, then find the request "
                    "POST api.flightyapp.com/v1/sync/full. Copy its "
                    "'Authorization' header value WITHOUT the leading 'Bearer ' "
                    "(the long token that starts with 'eyJ'). It is long-lived and "
                    "identifies your account."
                ),
                "x-input-type": "password",
                "x-no-reset": True,
                "default": "",
            },
            "build_token": {
                "type": "string",
                "title": "Build token",
                "description": (
                    "From the same POST /v1/sync/full request, copy the value of "
                    "the 'X-Flighty-Build-Token' header (also starts with 'eyJ'). "
                    "It is tied to the app version and stays valid for years."
                ),
                "x-input-type": "password",
                "x-no-reset": True,
                "default": "",
            },
            "device_id": {
                "type": "string",
                "title": "Device ID",
                "description": (
                    "From the same request, copy the 'Device' header value "
                    "(a UUID like 86E414FF-A71E-4300-BF75-AF9F7D768CBD)."
                ),
                "x-no-reset": True,
                "default": "",
            },
            "friend_names": {
                "type": "array",
                "title": "Friend names",
                "description": (
                    "Map each friend's owner ID (shown in the status panel below "
                    "after the first sync) to a display name for the LED wall."
                ),
                "x-input-type": "kv-list",
                "x-kv-key-label": "Owner ID",
                "x-kv-value-label": "Name",
                "items": {
                    "type": "object",
                    "properties": {
                        "uuid": {"type": "string", "default": ""},
                        "name": {"type": "string", "default": ""},
                    },
                },
                "default": [],
            },
            "cache_ttl_minutes": {
                "type": "number",
                "title": "Refresh interval (minutes)",
                "description": "How often to re-sync with Flighty.",
                "default": _DEFAULT_CACHE_TTL_MINUTES,
                "minimum": 1,
                "maximum": 120,
            },
            "api_base": {
                "type": "string",
                "title": "API base URL",
                "default": _DEFAULT_API_BASE,
                "x-internal": True,
            },
        },
    }

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._state: dict[str, Any] = {"cursor": None, "flights": {}, "airports": {}, "airlines": {}}
        self._loaded = False
        self._last_sync: float = 0.0

    # ── config helpers ──────────────────────────────────────────────────────

    def has_credentials(self) -> bool:
        return bool(self.config.get("auth_token") and self.config.get("build_token"))

    def _cache_ttl(self) -> float:
        try:
            return max(60.0, float(self.config.get("cache_ttl_minutes", _DEFAULT_CACHE_TTL_MINUTES)) * 60.0)
        except (TypeError, ValueError):
            return _DEFAULT_CACHE_TTL_MINUTES * 60.0

    def friend_names(self) -> dict[str, str]:
        """Owner-UUID -> display name, from the user's ``friend_names`` config."""
        out: dict[str, str] = {}
        for row in self.config.get("friend_names") or []:
            if isinstance(row, dict) and row.get("uuid"):
                out[str(row["uuid"])] = str(row.get("name", "") or "")
        return out

    _friend_names = friend_names  # backward-compatible internal alias

    def account_uuid(self) -> str:
        """The user's own owner UUID (the bearer token's ``sub``)."""
        return _account_uuid(str(self.config.get("auth_token", "")))

    # ── persistence ─────────────────────────────────────────────────────────

    def _load_state(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if _STATE_PATH.exists():
                self._state = json.loads(_STATE_PATH.read_text())
                self._state.setdefault("flights", {})
                self._state.setdefault("airports", {})
                self._state.setdefault("airlines", {})
                self._last_sync = float(self._state.get("last_sync", 0.0))
        except (OSError, ValueError) as exc:
            logger.warning("Flighty: could not load state: %s", exc)

    def _save_state(self) -> None:
        try:
            _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._state["last_sync"] = self._last_sync
            tmp = _STATE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._state))
            tmp.replace(_STATE_PATH)
        except OSError as exc:
            logger.warning("Flighty: could not save state: %s", exc)

    # ── sync ────────────────────────────────────────────────────────────────

    def _initial_cursor(self) -> str:
        now = int(time.time())
        cursor: dict[str, Any] = {"$sv": _SCHEMA_VERSION}
        for key in _CURSOR_FULL:
            cursor[key] = 0
        for key in _CURSOR_SKIP:
            cursor[key] = now
        cursor["p-flight"] = {}
        raw = json.dumps(cursor, separators=(",", ":")).encode()
        return base64.b64encode(raw).decode()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config['auth_token']}",
            "X-Flighty-Build-Token": str(self.config.get("build_token", "")),
            "Device": str(self.config.get("device_id", "")),
            "Accept": "application/x-protobuf",
            "Content-Type": "application/x-protobuf",
            "X-Flighty-Locale": "en_US",
            "User-Agent": "Flighty 4.11.0 (4813) com.flightyapp.flighty",
        }

    async def _sync(self) -> bool:
        """Run one delta-sync, merging results into the local store. Returns success."""
        cursor = self._state.get("cursor") or self._initial_cursor()
        base = str(self.config.get("api_base") or _DEFAULT_API_BASE).rstrip("/")
        url = f"{base}/v1/sync/full"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, params={"token": cursor}, headers=self._headers())
            if resp.status_code != 200:
                logger.warning("Flighty sync HTTP %d: %s", resp.status_code, resp.text[:200])
                return False
            parsed = parse_sync_response(resp.content)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Flighty sync failed: %s", exc)
            return False

        for uuid, fl in parsed.flights.items():
            self._state["flights"][uuid] = fl
        self._state["airports"].update(parsed.airports)
        self._state["airlines"].update(parsed.airlines)
        if parsed.next_cursor and self._state["flights"]:
            # Only persist the advanced cursor once we actually hold flights, so a
            # transient empty/500 first response can't strand us on a "caught up"
            # cursor with an empty store — the next sync then re-runs the initial
            # full request instead.
            self._state["cursor"] = parsed.next_cursor
        elif not self._state["flights"]:
            self._state["cursor"] = None
        self._last_sync = time.time()
        self._save_state()
        logger.info(
            "Flighty sync: +%d flights (store=%d), %d airports, %d airlines",
            len(parsed.flights), len(self._state["flights"]),
            len(self._state["airports"]), len(self._state["airlines"]),
        )
        return True

    # ── public API ──────────────────────────────────────────────────────────

    def _normalize(self, fl: dict[str, Any], now: float) -> dict[str, Any]:
        """Map a raw parsed flight to the Flight Tracker ``_tracked`` shape."""
        airlines = self._state["airlines"]
        airports = self._state["airports"]
        iata = airlines.get(fl.get("airline_uuid", ""), "")
        origin = airports.get(fl.get("origin_uuid", ""), "")
        dest = airports.get(fl.get("dest_uuid", ""), "")
        number = fl.get("number", "")
        ident = f"{iata}{number}" if iata and number else number

        sched_off, est_off = fl.get("sched_off"), fl.get("est_off")
        sched_on, est_on = fl.get("sched_on"), fl.get("est_on")
        eff_off = est_off or sched_off
        eff_on = est_on or sched_on
        # Phase is derived from the clock against best-known times so the card
        # transitions scheduled -> airborne -> landed without a live feed.
        actual_off = _iso(eff_off) if eff_off and now >= eff_off else None
        actual_on = _iso(eff_on) if eff_on and now >= eff_on else None
        dep_delay = (est_off - sched_off) if (est_off and sched_off) else None
        arr_delay = (est_on - sched_on) if (est_on and sched_on) else None

        return {
            "found": True,
            "ident": ident,
            "number": ident,
            "owner": fl.get("owner", ""),
            "origin": origin,
            "dest": dest,
            "airline": iata,
            "operator_iata": iata,
            "aircraft_type": fl.get("aircraft_icao", ""),
            "status": "",
            "cancelled": bool(fl.get("cancelled")),
            "scheduled_off": _iso(sched_off),
            "estimated_off": _iso(est_off),
            "actual_off": actual_off,
            "scheduled_on": _iso(sched_on),
            "estimated_on": _iso(est_on),
            "actual_on": actual_on,
            "departure_delay": dep_delay,
            "arrival_delay": arr_delay,
            "progress_percent": None,
            "live": None,
            "icao24": "",
            "gate_origin": fl.get("dep_gate", ""),
            "gate_dest": fl.get("arr_gate", ""),
            "terminal_origin": fl.get("dep_terminal", ""),
            "terminal_dest": fl.get("arr_terminal", ""),
            "baggage_claim": fl.get("arr_baggage", ""),
            "date": (_iso(sched_off) or "")[:10],
        }

    async def fetch_flights(self, include_friends: bool = True) -> list[dict[str, Any]] | None:
        """Return upcoming flights (normalized) sorted by departure, or None on failure.

        Own flights always included; friends' flights only when ``include_friends``.
        ``None`` means the sync failed and there is no cached data (callers keep
        their last result on ``None``).
        """
        self._load_state()
        if not self.has_credentials():
            return None
        if time.time() - self._last_sync >= self._cache_ttl() or not self._state["flights"]:
            ok = await self._sync()
            if not ok and not self._state["flights"]:
                return None

        me = _account_uuid(str(self.config.get("auth_token", "")))
        now = time.time()
        out: list[dict[str, Any]] = []
        for fl in self._state["flights"].values():
            if not include_friends and fl.get("owner") != me:
                continue
            sched = fl.get("sched_off")
            if not sched or sched < now - _PAST_WINDOW_S:
                continue
            out.append(self._normalize(fl, now))
        out.sort(key=lambda f: f.get("scheduled_off") or "")
        return out

    def owner_summary(self) -> list[dict[str, Any]]:
        """Distinct owners with upcoming counts, for the settings UI to label."""
        self._load_state()
        me = _account_uuid(str(self.config.get("auth_token", "")))
        now = time.time()
        names = self._friend_names()
        counts: dict[str, int] = {}
        for fl in self._state["flights"].values():
            sched = fl.get("sched_off")
            if sched and sched >= now - _PAST_WINDOW_S:
                counts[fl.get("owner", "")] = counts.get(fl.get("owner", ""), 0) + 1
        rows = []
        for uuid, cnt in sorted(counts.items(), key=lambda kv: -kv[1]):
            label = "You" if uuid == me else (names.get(uuid) or "(unnamed)")
            rows.append({"uuid": uuid, "label": label, "upcoming": cnt})
        return rows

    def get_status(self) -> dict[str, Any] | None:
        self._load_state()
        if not self.has_credentials() and not self._state["flights"]:
            return None
        items = [
            {"label": "Flights in store", "value": len(self._state["flights"])},
            {"label": "Airports cached", "value": len(self._state["airports"])},
            {"label": "Airlines cached", "value": len(self._state["airlines"])},
        ]
        if self._last_sync:
            items.append({"label": "Last sync", "value": int(self._last_sync), "kind": "timestamp"})
        owners = [
            {"label": f"{r['label']} — {r['uuid']}", "value": f"{r['upcoming']} upcoming"}
            for r in self.owner_summary()
        ]
        sections = [{"label": "Sync", "items": items}]
        if owners:
            sections.append({"label": "Owners (map friend IDs to names above)", "items": owners})
        note = None if self.has_credentials() else "No credentials configured — add tokens above."
        return {"note": note, "sections": sections}
