"""Pure-Python parser for Flighty's ``/v1/sync/full`` protobuf response.

Flighty has no public API; this decodes the ``application/x-protobuf`` body of
``POST https://api.flightyapp.com/v1/sync/full`` (message
``com.flighty.api.proto.response.SyncResponseProto``) using only the wire format,
so the engine needs no protobuf compiler or ``protobuf`` dependency.

Field numbers were reverse-engineered from a real sync capture (see
``engine/libraries/flighty/README.md``). Only the fields the LED display needs
are decoded; everything else is skipped. The response is a delta-sync:

    SyncResponseProto {
      1: Meta { 1: next_cursor_url (string) }
      2: repeated Entity   # oneof by inner field number:
           5:  Airport      # id -> IATA table
           15: Flight       # the flights (own + friends', tagged by owner)
           22: AircraftType
           14: User, 11: UserSubscription, ...
    }

    Flight (Entity#15) {
      1: uuid
      2: FlightDetail
      9: owner user UUID     # distinguishes own vs friends' flights
      10: live.flighty.app URL
    }
    FlightDetail (Flight#2) {
      2:  Departure { 2: terminal, 3: gate, 4: TimeBlock, 11: airport_uuid }
      3:  Arrival   { 3: terminal, 4: gate, 5: baggage, 7: TimeBlock, 13/14: airport_uuid }
      5:  cancelled flag (varint, present/1 only on cancelled flights)
      6:  repeated FlightNumber { 2: number, 3: is_primary, 4: airline_uuid }
      7:  Aircraft  { 1: tail, 2: type_name, 6: icao_type }
      16: primary flight number (string, digits)
      21: primary airline UUID
    }
    TimeBlock { 1: scheduled, 2: estimated, 3: actual, ... each = { 1: epoch_seconds } }
    Airport (Entity#5 -> #4) { 1: uuid, 3: IATA, 4: ICAO, 5: tz, 7: city }
    Airline (embedded in flight legs) { 1: uuid, 3: IATA, 4: ICAO, 2: name }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Wire-format primitives ──────────────────────────────────────────────────

def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = 0
    result = 0
    n = len(buf)
    while True:
        if i >= n:
            raise ValueError("truncated varint")
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def iter_fields(buf: bytes):
    """Yield ``(field_number, wire_type, value)`` for one protobuf message.

    ``value`` is an ``int`` for varint/fixed wire types and ``bytes`` for
    length-delimited fields. Raises ``ValueError`` on malformed input so callers
    can treat a blob as "not a message".
    """
    i = 0
    n = len(buf)
    while i < n:
        tag, i = _read_varint(buf, i)
        fnum = tag >> 3
        wt = tag & 7
        if fnum == 0:
            raise ValueError("zero field number")
        if wt == 0:
            val, i = _read_varint(buf, i)
            yield fnum, wt, val
        elif wt == 2:
            ln, i = _read_varint(buf, i)
            if i + ln > n:
                raise ValueError("truncated length-delimited field")
            yield fnum, wt, buf[i:i + ln]
            i += ln
        elif wt == 1:
            if i + 8 > n:
                raise ValueError("truncated 64-bit field")
            yield fnum, wt, buf[i:i + 8]
            i += 8
        elif wt == 5:
            if i + 4 > n:
                raise ValueError("truncated 32-bit field")
            yield fnum, wt, buf[i:i + 4]
            i += 4
        else:
            raise ValueError(f"unsupported wire type {wt}")


def field_map(buf: bytes) -> dict[int, list[tuple[int, Any]]]:
    """Parse a message into ``{field_number: [(wire_type, value), ...]}``.

    Returns an empty dict if ``buf`` is not a well-formed message, so it is safe
    to attempt on any length-delimited value.
    """
    out: dict[int, list[tuple[int, Any]]] = {}
    try:
        for fnum, wt, val in iter_fields(buf):
            out.setdefault(fnum, []).append((wt, val))
    except ValueError:
        return {}
    return out


def _first(fm: dict[int, list[tuple[int, Any]]], num: int):
    lst = fm.get(num)
    return lst[0][1] if lst else None


def _str(fm: dict[int, list[tuple[int, Any]]], num: int) -> str:
    v = _first(fm, num)
    if not isinstance(v, (bytes, bytearray)):
        return ""
    try:
        s = v.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    return s if all(31 < ord(c) < 127 or c in "\t /.:_-+@" for c in s) else ""


def _epoch_from_time(fm: dict[int, list[tuple[int, Any]]], num: int) -> int | None:
    """A time slot is ``{1: epoch_seconds}``; return the epoch or None."""
    sub = _first(fm, num)
    if not isinstance(sub, (bytes, bytearray)):
        return None
    tm = field_map(sub)
    sec = _first(tm, 1)
    return sec if isinstance(sec, int) and sec > 0 else None


# ── High-level parse ────────────────────────────────────────────────────────

@dataclass
class ParsedSync:
    next_cursor: str | None = None
    # flight uuid -> raw normalized flight dict (airport/airline still UUIDs)
    flights: dict[str, dict[str, Any]] = field(default_factory=dict)
    airports: dict[str, str] = field(default_factory=dict)   # uuid -> IATA
    airlines: dict[str, str] = field(default_factory=dict)   # uuid -> IATA


def _collect_airlines(fm: dict[int, list[tuple[int, Any]]], out: dict[str, str], depth: int = 0) -> None:
    """Recursively harvest embedded Airline objects ({1:uuid,2:name,3:iata,4:icao}).

    Flight records embed the airline object inside leg/segment sub-messages, so
    scanning the flight detail yields a UUID->IATA map without a separate airline
    reference fetch.
    """
    if depth > 6:
        return
    uuid = _str(fm, 1)
    name = _str(fm, 2)
    iata = _str(fm, 3)
    icao = _str(fm, 4)
    if uuid and "-" in uuid and name and 1 <= len(iata) <= 3 and len(icao) == 3:
        out.setdefault(uuid, iata)
    for lst in fm.values():
        for wt, val in lst:
            if wt == 2 and isinstance(val, (bytes, bytearray)) and len(val) >= 4:
                child = field_map(val)
                if child:
                    _collect_airlines(child, out, depth + 1)


def _parse_airport_entity(entity_body: bytes, airports: dict[str, str]) -> None:
    """Entity#5 wraps an Airport at #4: {1:uuid, 3:IATA, ...}."""
    ent = field_map(entity_body)
    ap = _first(ent, 4)
    if not isinstance(ap, (bytes, bytearray)):
        return
    apm = field_map(ap)
    uuid = _str(apm, 1)
    iata = _str(apm, 3)
    if uuid and iata:
        airports[uuid] = iata


def _parse_flight_entity(entity_body: bytes, airlines: dict[str, str]) -> dict[str, Any] | None:
    fl = field_map(entity_body)
    uuid = _str(fl, 1)
    if not uuid:
        return None
    detail_raw = _first(fl, 2)
    if not isinstance(detail_raw, (bytes, bytearray)):
        return None
    det = field_map(detail_raw)

    _collect_airlines(det, airlines)

    number = _str(det, 16)
    airline_uuid = _str(det, 21)

    dep = field_map(_first(det, 2) or b"")
    arr = field_map(_first(det, 3) or b"")
    dep_times = field_map(_first(dep, 4) or b"")
    arr_times = field_map(_first(arr, 7) or b"")

    return {
        "flight_uuid": uuid,
        "owner": _str(fl, 9),
        "number": number,
        "airline_uuid": airline_uuid,
        # FlightDetail #5 is a cancelled flag (present/1 only on cancelled flights).
        "cancelled": bool(_first(det, 5)),
        "origin_uuid": _str(dep, 11),
        "dest_uuid": _str(arr, 13) or _str(arr, 14),
        "dep_terminal": _str(dep, 2),
        "dep_gate": _str(dep, 3),
        "arr_terminal": _str(arr, 3),
        "arr_gate": _str(arr, 4),
        "arr_baggage": _str(arr, 5),
        # time block slots: 1=scheduled, 2=estimated, 3=actual (epoch seconds)
        "sched_off": _epoch_from_time(dep_times, 1),
        "est_off": _epoch_from_time(dep_times, 2),
        "act_off": _epoch_from_time(dep_times, 3),
        "sched_on": _epoch_from_time(arr_times, 1),
        "est_on": _epoch_from_time(arr_times, 2),
        "act_on": _epoch_from_time(arr_times, 3),
        "aircraft_icao": _str(field_map(_first(det, 7) or b""), 6),
        "live_url": _str(fl, 10),
    }


def parse_sync_response(data: bytes) -> ParsedSync:
    """Parse a SyncResponseProto body into a :class:`ParsedSync`."""
    result = ParsedSync()
    root = field_map(data)

    meta = _first(root, 1)
    if isinstance(meta, (bytes, bytearray)):
        cursor = _str(field_map(meta), 1)
        if cursor:
            result.next_cursor = cursor

    for wt, val in root.get(2, []):
        if wt != 2 or not isinstance(val, (bytes, bytearray)):
            continue
        ent = field_map(val)
        if 15 in ent:  # Flight
            body = ent[15][0][1]
            if isinstance(body, (bytes, bytearray)):
                fr = _parse_flight_entity(body, result.airlines)
                if fr:
                    result.flights[fr["flight_uuid"]] = fr
        elif 5 in ent:  # Airport
            body = ent[5][0][1]
            if isinstance(body, (bytes, bytearray)):
                _parse_airport_entity(body, result.airports)

    return result
