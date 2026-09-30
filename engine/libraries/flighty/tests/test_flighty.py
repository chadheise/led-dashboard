"""Flighty sync parsing + normalization, driven by a synthetic protobuf body.

The real capture used to reverse-engineer the schema contains personal flight
data and is not committed; instead these tests build a tiny ``SyncResponseProto``
by hand (see ``_encode`` helpers) covering the fields the LED display consumes:
own vs friends' flights, airline/airport resolution, gate/terminal/baggage, and
schedule-derived delay/phase.
"""

from __future__ import annotations

import base64
import json
import time

import pytest

from libraries.flighty import library as flighty_lib
from libraries.flighty.library import FlightyLibrary, _account_uuid
from libraries.flighty.sync_parser import parse_sync_response


# ── minimal protobuf encoder ────────────────────────────────────────────────

def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _ld(field: int, data: bytes) -> bytes:
    """A length-delimited (wire type 2) field."""
    return _varint((field << 3) | 2) + _varint(len(data)) + data


def _vint(field: int, value: int) -> bytes:
    return _varint((field << 3) | 0) + _varint(value)


def _s(field: int, text: str) -> bytes:
    return _ld(field, text.encode())


def _time(field: int, epoch: int) -> bytes:
    return _ld(field, _vint(1, epoch))


ME = "11111111-1111-1111-1111-111111111111"
FRIEND = "22222222-2222-2222-2222-222222222222"
AIRLINE = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
JFK = "jjjjjjjj-jjjj-jjjj-jjjj-jjjjjjjjjjjj"
LAX = "llllllll-llll-llll-llll-llllllllllll"


def _airline_obj() -> bytes:
    return _s(1, AIRLINE) + _s(2, "Delta") + _s(3, "DL") + _s(4, "DAL")


def _flight(uuid: str, owner: str, number: str, sched_off: int, est_off: int,
            sched_on: int, est_on: int, *, dep_gate="", dep_term="",
            arr_term="", arr_gate="", arr_bag="", cancelled=False) -> bytes:
    dep = (
        _s(2, dep_term) + _s(3, dep_gate)
        + _ld(4, _time(1, sched_off) + _time(2, est_off))
        + _s(11, JFK)
    )
    arr = (
        _s(3, arr_term) + _s(4, arr_gate) + _s(5, arr_bag)
        + _ld(7, _time(1, sched_on) + _time(2, est_on))
        + _s(13, LAX)
    )
    detail = (
        _ld(2, dep) + _ld(3, arr)
        + (_vint(5, 1) if cancelled else b"")                     # cancelled flag
        + _ld(6, _s(2, number) + _vint(3, 1) + _s(4, AIRLINE))   # primary number
        + _ld(7, _s(6, "B739"))                                   # aircraft
        + _ld(10, _ld(4, _airline_obj()))                        # embedded airline (leg)
        + _s(16, number) + _s(21, AIRLINE)
    )
    return _ld(1, uuid.encode()) and (_s(1, uuid) + _ld(2, detail) + _s(9, owner)
                                      + _s(10, f"https://live.flighty.app/{uuid}"))


def _airport_entity(uuid: str, iata: str) -> bytes:
    # Entity#5 body carries the Airport object at field #4 ({1:uuid, 3:IATA}).
    return _ld(2, _ld(5, _ld(4, _s(1, uuid) + _s(3, iata))))


def _flight_entity(*args, **kwargs) -> bytes:
    return _ld(2, _ld(15, _flight(*args, **kwargs)))


def _sync_body(next_cursor: str, flights: list[bytes], airports: list[bytes]) -> bytes:
    root = _ld(1, _s(1, next_cursor))
    for ap in airports:
        root += ap
    for fl in flights:
        root += fl
    return root


def _jwt(sub: str) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": sub, "iss": "flighty-api", "iat": 1514764800}).encode()
    ).rstrip(b"=").decode()
    return f"h.{payload}.s"


NOW = int(time.time())


def _body_two_flights() -> bytes:
    return _sync_body(
        "CURSOR2",
        [
            # my upcoming flight, full gate/terminal/baggage, 12-min delay
            _flight_entity("f-mine", ME, "2437", NOW + 3600, NOW + 3600 + 720,
                           NOW + 3600 * 4, NOW + 3600 * 4 + 720,
                           dep_gate="B6", dep_term="4", arr_term="1", arr_gate="F6", arr_bag="10"),
            # friend's upcoming flight
            _flight_entity("f-friend", FRIEND, "2004", NOW + 7200, NOW + 7200,
                           NOW + 7200 * 2, NOW + 7200 * 2, arr_term="3"),
            # a past flight (should be filtered out of upcoming)
            _flight_entity("f-old", ME, "1", NOW - 3600 * 24, NOW - 3600 * 24,
                           NOW - 3600 * 20, NOW - 3600 * 20),
        ],
        [_airport_entity(JFK, "JFK"), _airport_entity(LAX, "LAX")],
    )


# ── parser ──────────────────────────────────────────────────────────────────

def test_parser_extracts_flights_airports_airlines_and_cursor() -> None:
    parsed = parse_sync_response(_body_two_flights())
    assert parsed.next_cursor == "CURSOR2"
    assert parsed.airports == {JFK: "JFK", LAX: "LAX"}
    assert parsed.airlines == {AIRLINE: "DL"}
    assert set(parsed.flights) == {"f-mine", "f-friend", "f-old"}
    mine = parsed.flights["f-mine"]
    assert mine["owner"] == ME
    assert mine["number"] == "2437"
    assert (mine["dep_gate"], mine["dep_terminal"]) == ("B6", "4")
    assert (mine["arr_terminal"], mine["arr_gate"], mine["arr_baggage"]) == ("1", "F6", "10")


def test_parser_tolerates_garbage() -> None:
    assert parse_sync_response(b"\xff\xff\xff").flights == {}


def test_cancelled_flag_parsed_and_normalized() -> None:
    body = _sync_body(
        "C",
        [_flight_entity("f-x", ME, "99", NOW + 3600, NOW + 3600,
                        NOW + 7200, NOW + 7200, cancelled=True)],
        [],
    )
    parsed = parse_sync_response(body)
    assert parsed.flights["f-x"]["cancelled"] is True
    lib = FlightyLibrary({"auth_token": _jwt(ME)})
    normalized = lib._normalize(parsed.flights["f-x"], time.time())
    assert normalized["cancelled"] is True


# ── library normalization / fetch ───────────────────────────────────────────

@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(flighty_lib, "_STATE_PATH", tmp_path / "flighty_state.json")
    return FlightyLibrary({
        "auth_token": _jwt(ME), "build_token": "b", "device_id": "d",
        "friend_names": [{"uuid": FRIEND, "name": "Sam"}],
    })


def _preload(lib) -> None:
    parsed = parse_sync_response(_body_two_flights())
    lib._loaded = True
    lib._state = {"cursor": parsed.next_cursor, "flights": parsed.flights,
                  "airports": parsed.airports, "airlines": parsed.airlines}
    lib._last_sync = time.time()  # skip network


@pytest.mark.asyncio
async def test_fetch_flights_normalizes_and_filters(lib) -> None:
    _preload(lib)
    flights = await lib.fetch_flights(include_friends=True)
    idents = [f["ident"] for f in flights]
    assert idents == ["DL2437", "DL2004"]         # upcoming only, sorted; past dropped
    mine = flights[0]
    assert mine["owner"] == ME
    assert mine["origin"] == "JFK" and mine["dest"] == "LAX"
    assert mine["gate_origin"] == "B6" and mine["terminal_origin"] == "4"
    assert mine["gate_dest"] == "F6" and mine["baggage_claim"] == "10"
    assert mine["departure_delay"] == 720        # est - sched
    assert mine["scheduled_off"].endswith("Z")


@pytest.mark.asyncio
async def test_include_friends_toggle(lib) -> None:
    _preload(lib)
    own = await lib.fetch_flights(include_friends=False)
    assert [f["ident"] for f in own] == ["DL2437"]
    everyone = await lib.fetch_flights(include_friends=True)
    assert {f["owner"] for f in everyone} == {ME, FRIEND}


@pytest.mark.asyncio
async def test_fetch_without_credentials_returns_none(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(flighty_lib, "_STATE_PATH", tmp_path / "s.json")
    assert await FlightyLibrary({}).fetch_flights() is None


@pytest.mark.asyncio
async def test_sync_over_http_merges_and_advances_cursor(lib, monkeypatch) -> None:
    class _Resp:
        status_code = 200
        content = _body_two_flights()

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, params=None, headers=None):
            assert params["token"]           # initial cursor sent
            assert headers["Authorization"].startswith("Bearer ")
            return _Resp()

    monkeypatch.setattr(flighty_lib.httpx, "AsyncClient", _Client)
    flights = await lib.fetch_flights(include_friends=True)
    assert [f["ident"] for f in flights] == ["DL2437", "DL2004"]
    assert lib._state["cursor"] == "CURSOR2"     # advanced from server response


def test_owner_summary_labels_me_and_friends(lib) -> None:
    _preload(lib)
    rows = {r["uuid"]: r["label"] for r in lib.owner_summary()}
    assert rows[ME] == "You"
    assert rows[FRIEND] == "Sam"


def test_account_uuid_from_token() -> None:
    assert _account_uuid(_jwt(ME)) == ME
    assert _account_uuid("not-a-jwt") == ""
