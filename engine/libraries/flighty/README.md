# Flighty library

Imports the user's own and connected friends' upcoming flights from the
[Flighty](https://flighty.com) app — including gate, terminal, delay, and baggage
detail — for the Flight Tracker app's **Flighty** source.

Flighty has no public API and no username/password. This library speaks the same
private endpoint the iOS/macOS app uses. The account is identified by a
**long-lived bearer token** captured once from the app; there is no App Attest, so
the token replays off-device (from the Raspberry Pi) indefinitely.

## The API (reverse-engineered)

- `POST https://api.flightyapp.com/v1/sync/full?token=<base64url(JSON cursor)>` — a
  single delta-sync endpoint. Empty request body.
- Response: gzipped Protocol Buffers, message
  `com.flighty.api.proto.response.SyncResponseProto`. Parsed by
  [`sync_parser.py`](sync_parser.py) with a dependency-free wire-format reader (no
  `protoc`/`protobuf` needed).
- The `token` is a JSON map of entity → last-synced epoch; the response's field 1
  carries the next cursor to persist, so subsequent syncs are incremental. The
  library keeps `data/flighty_state.json` (cursor + accumulated flight and
  reference records).
- Flights (own **and** friends') arrive as `Flight` entities tagged with an owner
  UUID (`Flight` field 9). The user's own UUID is the bearer token's `sub` claim.

Headers required (all captured from the app; long-lived):

| Header | Purpose |
|---|---|
| `Authorization: Bearer <JWT>` | Account identity (`sub` = owner UUID). No expiry. |
| `X-Flighty-Build-Token: <JWT>` | App build attestation (valid for years). |
| `Device: <UUID>` | Static device id. |

## Getting the tokens (one-time capture)

1. Run an intercepting HTTPS proxy (Proxyman / mitmproxy / Charles) in front of a
   device running Flighty (the macOS app is easiest; defeat TLS pinning as needed).
2. Open Flighty and let it sync. Find the `POST /v1/sync/full` request.
3. Copy the `Authorization` bearer value, the `X-Flighty-Build-Token` value, and the
   `Device` UUID into the Flighty library settings.

Enter them in the LED dashboard under Settings → Flighty. After the first sync the
status panel lists each owner UUID with its upcoming-flight count; map the friends'
UUIDs to display names there (own flights are auto-labeled "You").

## Notes

- Read-only: the sync request sends no body and never modifies the Flighty account.
- Tokens are stored (like other library credentials) in `data/state.json`
  (gitignored). They are secrets — do not commit captured values.
- The schema field map is documented at the top of `sync_parser.py`. It was derived
  from a real capture; if a Flighty app update changes it, only that module needs
  updating. Tests use a synthetic protobuf body, not real personal data.
