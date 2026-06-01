#!/usr/bin/env python3
"""
One-time OAuth helper to obtain a Spotify refresh token.

Run this script once from your terminal:
    python get_refresh_token.py

It will:
  1. Ask for your Spotify Client ID and Client Secret
  2. Open (or print) an authorization URL for you to visit in a browser
  3. Start a local HTTP server on port 8888 to receive the OAuth callback
  4. Exchange the authorization code for tokens
  5. Print your refresh token to paste into the LED dashboard Settings page

Prerequisites:
  - pip install httpx  (or: the engine's venv already includes httpx)
  - Your Spotify app must have http://localhost:8888/callback as a Redirect URI
    (set this in your Spotify Developer Dashboard)
"""

import base64
import http.server
import os
import sys
import urllib.parse
import urllib.request
import webbrowser

# ---------------------------------------------------------------------------
# Try to use httpx if available; fall back to urllib for the token exchange.
# ---------------------------------------------------------------------------
try:
    import httpx as _httpx  # noqa: F401
    _USE_HTTPX = True
except ImportError:
    _USE_HTTPX = False

_REDIRECT_URI = "http://localhost:8888/callback"
_AUTH_URL = "https://accounts.spotify.com/authorize"
_TOKEN_URL = "https://accounts.spotify.com/api/token"
_SCOPE = "user-read-playback-state"

_auth_code: str | None = None


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        global _auth_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            _auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Authorization successful!</h2>"
                b"<p>You can close this tab and return to your terminal.</p></body></html>"
            )
        else:
            error = params.get("error", ["unknown"])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                f"<html><body><h2>Authorization failed: {error}</h2></body></html>".encode()
            )

    def log_message(self, *args: object) -> None:
        pass  # suppress access log noise


def _exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _REDIRECT_URI,
        }
    ).encode()

    req = urllib.request.Request(_TOKEN_URL, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        import json
        return json.loads(resp.read())


def main() -> None:
    print("=" * 60)
    print("Spotify Refresh Token Setup")
    print("=" * 60)
    print()

    client_id = os.environ.get("SPOTIFY_CLIENT_ID") or input("Client ID: ").strip()
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET") or input("Client Secret: ").strip()

    if not client_id or not client_secret:
        print("ERROR: Client ID and Client Secret are required.")
        sys.exit(1)

    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": _REDIRECT_URI,
            "scope": _SCOPE,
        }
    )
    auth_url = f"{_AUTH_URL}?{params}"

    print()
    print("Opening authorization URL in your browser…")
    print("If it doesn't open automatically, paste this URL manually:")
    print()
    print(f"  {auth_url}")
    print()
    webbrowser.open(auth_url)

    print("Waiting for Spotify to redirect to http://localhost:8888/callback …")
    server = http.server.HTTPServer(("localhost", 8888), _CallbackHandler)
    server.handle_request()  # handles exactly one request (the callback)

    if not _auth_code:
        print("ERROR: Did not receive an authorization code. Please try again.")
        sys.exit(1)

    print("Authorization code received. Exchanging for tokens…")
    try:
        tokens = _exchange_code(client_id, client_secret, _auth_code)
    except Exception as exc:
        print(f"ERROR: Token exchange failed: {exc}")
        sys.exit(1)

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print(f"ERROR: No refresh token in response: {tokens}")
        sys.exit(1)

    print()
    print("=" * 60)
    print("SUCCESS!  Your refresh token is:")
    print()
    print(f"  {refresh_token}")
    print()
    print("Next steps:")
    print("  1. Open the LED dashboard UI → Settings")
    print("  2. Find the 'Spotify' library section")
    print("  3. Paste your Client ID, Client Secret, and the Refresh Token above")
    print("  4. Save and add a 'Spotify Now Playing' module to your playlist")
    print("=" * 60)


if __name__ == "__main__":
    main()
