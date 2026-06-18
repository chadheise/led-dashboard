from __future__ import annotations

import base64
import time
from io import BytesIO
from pathlib import Path
from typing import Any, ClassVar

import httpx
from PIL import Image

from libraries.base import Library


_TOKEN_URL = "https://accounts.spotify.com/api/token"
_NOW_PLAYING_URL = "https://api.spotify.com/v1/me/player/currently-playing"
_TOKEN_EXPIRY_BUFFER = 60  # refresh 60s before actual expiry


class SpotifyLibrary(Library):
    id: ClassVar[str] = "spotify"
    name: ClassVar[str] = "Spotify"
    description: ClassVar[str] = (
        "Spotify Web API integration for now-playing track data. "
        "Requires a one-time OAuth setup — see the Spotify app README."
    )
    icon: ClassVar[str] = (Path(__file__).parent / "icon.svg").read_text()
    global_config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Spotify API Credentials",
        "properties": {
            "client_id": {
                "type": "string",
                "title": "Client ID",
                "description": "From your Spotify Developer Dashboard app",
            },
            "client_secret": {
                "type": "string",
                "title": "Client Secret",
                "description": "From your Spotify Developer Dashboard app",
                "x-input-type": "password",
            },
            "refresh_token": {
                "type": "string",
                "title": "Refresh Token",
                "description": "Obtained by running get_refresh_token.py once",
                "x-input-type": "password",
            },
        },
        "required": ["client_id", "client_secret", "refresh_token"],
    }

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    def _credentials_present(self) -> bool:
        return bool(
            self.config.get("client_id")
            and self.config.get("client_secret")
            and self.config.get("refresh_token")
        )

    async def _ensure_token(self) -> None:
        if not self._credentials_present():
            raise RuntimeError("Spotify credentials not configured")
        if self._access_token and time.time() < self._token_expires_at - _TOKEN_EXPIRY_BUFFER:
            return

        client_id = self.config["client_id"]
        client_secret = self.config["client_secret"]
        refresh_token = self.config["refresh_token"]

        encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _TOKEN_URL,
                headers={
                    "Authorization": f"Basic {encoded}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + int(data.get("expires_in", 3600))

    async def get_currently_playing(self) -> dict[str, Any] | None:
        """Return normalized now-playing data, or None if nothing is playing."""
        await self._ensure_token()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _NOW_PLAYING_URL,
                headers={"Authorization": f"Bearer {self._access_token}"},
            )

        if resp.status_code == 204:
            return None
        resp.raise_for_status()

        data = resp.json()
        if data.get("currently_playing_type") != "track":
            return None

        item = data.get("item") or {}
        artists = item.get("artists") or []
        artist = ", ".join(a["name"] for a in artists) if artists else ""
        album = (item.get("album") or {}).get("name", "")

        # Pick smallest available album art image
        images = (item.get("album") or {}).get("images") or []
        art_url: str | None = None
        if images:
            smallest = min(images, key=lambda img: img.get("width") or 9999)
            art_url = smallest.get("url")

        return {
            "title": item.get("name", ""),
            "artist": artist,
            "album": album,
            "album_art_url": art_url,
            "progress_ms": int(data.get("progress_ms") or 0),
            "duration_ms": int(item.get("duration_ms") or 0),
            "is_playing": bool(data.get("is_playing")),
        }

    async def fetch_album_art(self, url: str, size: int) -> Image.Image | None:
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                resp = await client.get(url)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            return img.resize((size, size), Image.LANCZOS)
        except Exception:
            return None
