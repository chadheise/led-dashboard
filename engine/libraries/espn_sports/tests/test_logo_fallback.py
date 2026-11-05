"""Team logos must survive a missing or dead ESPN logo URL.

The San Jose Sharks showed no logo: ESPN's scoreboard entry for the team did
not yield a usable image. ``fetch_logo`` now tries ESPN's alternate paths for
the same crest (with/without ``/scoreboard/``, and the abbreviation-keyed
default), the scoreboard parser fills in that default when ``team.logo`` is
absent, and a total failure is retried later instead of cached forever.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from libraries.espn_sports import library as lib
from libraries.espn_sports.library import ESPNSportsLibrary

SJ_SCOREBOARD = "https://a.espncdn.com/i/teamlogos/nhl/500/scoreboard/sj.png"
SJ_DEFAULT = "https://a.espncdn.com/i/teamlogos/nhl/500/sj.png"


def _make_lib(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, working: set[str]) -> tuple[ESPNSportsLibrary, list[str]]:
    espn = ESPNSportsLibrary({})
    espn._logo_dir = tmp_path
    calls: list[str] = []

    async def fake_download(url: str) -> Image.Image | None:
        calls.append(url)
        return Image.new("RGBA", (8, 8), (0, 128, 128, 255)) if url in working else None

    monkeypatch.setattr(espn, "_download_logo", fake_download)
    return espn, calls


def test_dead_scoreboard_url_falls_back_to_default(tmp_path, monkeypatch) -> None:
    espn, calls = _make_lib(tmp_path, monkeypatch, {SJ_DEFAULT})
    img = asyncio.run(espn.fetch_logo(SJ_SCOREBOARD, (64, 64), "nhl", "SJ"))
    assert img is not None
    assert calls == [SJ_SCOREBOARD, SJ_DEFAULT]
    assert (tmp_path / "nhl" / "SJ.png").exists()


def test_failure_is_retried_after_backoff(tmp_path, monkeypatch) -> None:
    working: set[str] = set()
    espn, calls = _make_lib(tmp_path, monkeypatch, working)
    assert asyncio.run(espn.fetch_logo(SJ_DEFAULT, (64, 64), "nhl", "SJ")) is None
    n = len(calls)
    # Within the backoff window: no new requests.
    assert asyncio.run(espn.fetch_logo(SJ_DEFAULT, (64, 64), "nhl", "SJ")) is None
    assert len(calls) == n
    # After it: retried, and succeeds once ESPN serves the image again.
    espn._logo_failed_at[SJ_DEFAULT] -= lib._LOGO_RETRY_SECONDS + 1
    working.add(SJ_DEFAULT)
    assert asyncio.run(espn.fetch_logo(SJ_DEFAULT, (64, 64), "nhl", "SJ")) is not None


def test_candidates() -> None:
    assert lib._logo_candidates(SJ_SCOREBOARD, "nhl", "SJ") == [SJ_SCOREBOARD, SJ_DEFAULT]
    assert lib._logo_candidates(SJ_DEFAULT, "nhl", "SJ") == [SJ_DEFAULT, SJ_SCOREBOARD]
    # Leagues without abbreviation-keyed logos get no invented URL.
    soccer = "https://a.espncdn.com/i/teamlogos/soccer/500/359.png"
    assert lib._logo_candidates(soccer, "eng.1", "ARS")[-1] != (
        "https://a.espncdn.com/i/teamlogos/eng.1/500/ars.png"
    )
    assert lib._default_logo_url("eng.1", "ARS") is None


class _FakeResponse:
    status_code = 200

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._data


class _FakeClient:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    async def get(self, url: str, params: dict[str, str] | None = None) -> _FakeResponse:
        return _FakeResponse(self._data)


def test_scoreboard_without_team_logo_gets_default_url() -> None:
    data = {
        "events": [{
            "id": "1",
            "competitions": [{
                "competitors": [
                    {"homeAway": "home", "score": "2",
                     "team": {"id": "18", "abbreviation": "SJ", "displayName": "San Jose Sharks"}},
                    {"homeAway": "away", "score": "1",
                     "team": {"id": "25", "abbreviation": "VGK", "displayName": "Vegas Golden Knights",
                              "logo": "https://a.espncdn.com/i/teamlogos/nhl/500/scoreboard/vgk.png"}},
                ],
            }],
        }]
    }
    games = asyncio.run(ESPNSportsLibrary({})._fetch_league(_FakeClient(data), "nhl"))
    assert games[0]["home_logo_url"] == SJ_DEFAULT
    assert games[0]["away_logo_url"] == "https://a.espncdn.com/i/teamlogos/nhl/500/scoreboard/vgk.png"


def test_houston_rockets_falls_back_to_default(tmp_path, monkeypatch) -> None:
    hou_default = "https://a.espncdn.com/i/teamlogos/nba/500/hou.png"
    espn, calls = _make_lib(tmp_path, monkeypatch, {hou_default})
    url = "https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/hou.png"
    assert asyncio.run(espn.fetch_logo(url, (64, 64), "nba", "HOU")) is not None
    assert calls[-1] == hou_default
