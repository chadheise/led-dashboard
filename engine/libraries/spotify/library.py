from __future__ import annotations

import base64
import time
from io import BytesIO
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
    icon: ClassVar[str] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">'
        '<path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0z'
        "m5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141"
        "-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32"
        ".42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58"
        "-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561"
        " 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301"
        "c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721"
        ' 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/>'
        "</svg>"
    )
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
