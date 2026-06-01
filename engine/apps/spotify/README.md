# Spotify Now Playing — Setup Guide

This app displays the track you're currently listening to on Spotify: scrolling title, artist name, album art thumbnail, and an optional progress bar.

Because Spotify requires user-level authorization to read playback state, you need to complete a one-time OAuth setup to obtain a **refresh token**. The app then uses this token silently going forward.

---

## Prerequisites

- A free or premium Spotify account
- Python 3 with the engine's virtualenv available (httpx is already installed)

---

## Step 1 — Create a Spotify Developer App

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and log in.
2. Click **Create app**.
3. Fill in any name and description (e.g. "LED Dashboard").
4. Set **Redirect URI** to:
   ```
   http://localhost:8888/callback
   ```
5. Under **APIs used**, check **Web API**.
6. Click **Save**.
7. Open your new app and click **Settings**. Copy your **Client ID** and **Client Secret**.

---

## Step 2 — Get a Refresh Token

Run the helper script from the `engine/apps/spotify/` directory (or any directory, as long as the engine's venv is active):

```bash
cd /path/to/led-dashboard/engine
.venv/bin/python apps/spotify/get_refresh_token.py
```

The script will:
1. Prompt you for your Client ID and Client Secret (or read them from `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` environment variables).
2. Open a browser tab pointing to Spotify's authorization page.
3. After you authorize, Spotify redirects to `http://localhost:8888/callback`.
4. The script exchanges the code for tokens and prints your **refresh token**.

> **Tip:** You can also set environment variables to skip the prompts:
> ```bash
> SPOTIFY_CLIENT_ID=abc123 SPOTIFY_CLIENT_SECRET=xyz789 \
>   .venv/bin/python apps/spotify/get_refresh_token.py
> ```

---

## Step 3 — Add Credentials to the Dashboard

1. Open the LED dashboard UI (usually `http://localhost:5173`).
2. Go to **Settings**.
3. Find the **Spotify** library section.
4. Paste in:
   - **Client ID** — from your Spotify Developer Dashboard app
   - **Client Secret** — from your Spotify Developer Dashboard app
   - **Refresh Token** — printed by `get_refresh_token.py`
5. Click **Save**.

---

## Step 4 — Add the App to a Playlist

1. In the UI, go to **Apps** and find **Spotify Now Playing**.
2. Add it as a module in any playlist.
3. Configure display options:
   | Option | Default | Description |
   |--------|---------|-------------|
   | Show album art | on | 32×32 px thumbnail on the left |
   | Show progress bar | on | 3-px bar at the bottom showing playback position |
   | Scroll speed | 2 | Pixels per frame for title/artist marquee |
   | Accent color | `#1DB954` | Color used for the artist name and progress bar |
   | Refresh interval | 10 s | How often to poll the Spotify API |

---

## Troubleshooting

**"Spotify credentials not configured"** — Open Settings and make sure all three credential fields are saved.

**"Not Playing" shown even when music is playing** — The Spotify API only reports playback from active devices. Make sure Spotify is open and actively playing (not paused). Podcasts and other non-track content are not shown.

**Token exchange fails** — Double-check that `http://localhost:8888/callback` is listed as a Redirect URI in your Spotify Developer Dashboard app settings.

**401 Unauthorized after some time** — The refresh token is permanent (it doesn't expire unless you revoke it). If you see 401 errors, verify the Client Secret is correct in Settings.

---

## Spotify API Reference

- [Web API overview](https://developer.spotify.com/documentation/web-api)
- [Access tokens & OAuth flows](https://developer.spotify.com/documentation/web-api/concepts/access-token)
- [Get currently playing track](https://developer.spotify.com/documentation/web-api/reference/get-the-users-currently-playing-track)
- [Authorization Code Flow](https://developer.spotify.com/documentation/web-api/tutorials/code-flow)
