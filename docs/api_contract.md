# iWitness API contract

The agreement between `client/` and `server/`. The frontend builds against a mock that follows this document exactly, then switches to the real backend by changing one setting. If either side needs a change, edit this file first and tell the other side.

Scope follows [project_brief.md](project_brief.md): five permitted I-95 cameras, anonymous trips, a 5-hour loop buffer per camera, an incident button that works signed out, and Google sign-in to save.

## Conventions

- **Paths.** The backend serves paths as written below (`/cameras`). The client calls them with an `/api` prefix (`/api/cameras`); the Vite proxy strips it.
- **JSON.** Request and response bodies are JSON, except `DELETE`, which returns `204 No Content`. Field names are `snake_case` on the wire and in client types, so no mapping layer is needed.
- **Times.** Every timestamp is an ISO 8601 string in UTC, for example `"2026-09-26T18:04:12Z"`. The server stamps times; the client never sends a time it wants trusted.
- **IDs.** Opaque strings (UUIDs). The client never builds or parses them.
- **Nullable fields** are always present with `null`, never omitted.

## Headers

| Header | When | Value |
| --- | --- | --- |
| `Authorization` | Any request while signed in | `Bearer <Supabase access token>` |
| `X-Trip-Token` | Any request about a trip the browser started | The `trip_token` from `POST /trips` |

The backend derives the user from the verified access token. **No endpoint accepts a user ID in the body or query.**

## Errors

Non-2xx responses use FastAPI's default body:

```json
{ "detail": "Human-readable message" }
```

| Status | Meaning |
| --- | --- |
| 400 | Malformed request |
| 401 | Sign-in required, or access token invalid |
| 403 | Trip token missing or wrong |
| 404 | Not found, **or not yours** (never reveal that someone else's incident exists) |
| 409 | Conflict: incident already claimed, or clip not ready yet |
| 410 | Unclaimed incident expired; its video is deleted |

## Types

```ts
type IsoTime = string

// "replay" = saved recording fed through the same pipeline. UI must label it.
type SourceType = 'live' | 'replay'

interface Camera {
  id: string
  name: string            // e.g. "I-95 at NW 79 St"
  location: string        // mile marker / direction / cross street
  source_type: SourceType
  recording: boolean      // false if the recorder for this camera is down
}

type TripState = 'active' | 'ended'

interface Trip {
  id: string
  camera_id: string
  started_at: IsoTime
  ended_at: IsoTime | null
  state: TripState
}

interface StartTripResponse {
  trip: Trip
  trip_token: string      // returned once; client stores it
}

interface BufferInfo {
  camera_id: string
  playlist_url: string    // hand straight to the player; already authorized
  earliest: IsoTime | null  // oldest footage currently in the loop
  latest: IsoTime | null    // live edge
}

// recording   post-trigger window still being recorded
// assembling  concatenating segments into clip.mp4
// uploading   copying the clip to private storage (after claim)
// ready       playable and downloadable
// failed      see `error`
type ProcessingState = 'recording' | 'assembling' | 'uploading' | 'ready' | 'failed'

// unclaimed   pressed while signed out; waiting for sign-in until expires_at
// claimed     attached to the signed-in user
// expired     never claimed in time; video deleted
type ClaimState = 'unclaimed' | 'claimed' | 'expired'

interface Incident {
  id: string
  trip_id: string
  camera_id: string
  camera_name: string
  source_type: SourceType
  trigger_at: IsoTime            // server time of the press
  requested_start: IsoTime       // trigger_at - pre-trigger window (default 60 s)
  requested_end: IsoTime         // trigger_at + post-trigger window (default 15 s)
  actual_start: IsoTime | null   // what the clip really covers, by our recording
  actual_end: IsoTime | null     // clock; show these, not requested_*. Null until known.
  source_start: IsoTime | null   // same span by the camera's own clock, if the
  source_end: IsoTime | null     // source provides one. Never mixed with actual_*.
  duration_seconds: number | null  // null until the clip is assembled
  size_bytes: number | null        // null until the clip is assembled
  sha256: string | null            // hex, of the saved file; null until ready
  processing_state: ProcessingState
  claim_state: ClaimState
  expires_at: IsoTime | null     // only while unclaimed
  video_version: number          // bumps if the clip is replaced
  error: string | null
  thumbnail_url: string | null   // JPEG still from the clip at the press; short-lived
                                 // signed link, owner only. Null until ready.
  deletes_at: IsoTime | null     // when a saved clip is deleted automatically:
                                 // trigger_at + 30 days. Null unless claimed.
}

interface Playback {
  incident_id: string
  video_version: number
  playback_url: string    // short-lived signed URL (or authenticated local URL offline)
  download_url: string    // same file, served as an attachment
  expires_at: IsoTime
}

interface User {
  id: string
  email: string
  display_name: string | null
  avatar_url: string | null
}
```

`Incident` never includes `user_id` or the storage path.

UI wording rules for these fields: label `source_*` as the camera's clock and `actual_*` as our recording time. Label `sha256` as showing the saved file is unchanged since we stored it, not what happened on the road.

## Endpoints

### Anonymous (no sign-in needed)

| Method and path | Headers | Body | Returns |
| --- | --- | --- | --- |
| `GET /cameras` | none | none | `Camera[]`, only permitted cameras |
| `POST /trips` | `Authorization` optional | `{ "camera_id": string }` | `StartTripResponse` |
| `POST /trips/{trip_id}/end` | `X-Trip-Token` | none | `Trip` |
| `GET /trips/{trip_id}/buffer` | `X-Trip-Token` | none | `BufferInfo` |
| `POST /trips/{trip_id}/incidents` | `X-Trip-Token`, `Authorization` optional | none | `Incident` |

- `POST /trips` while signed in sets the trip's owner; the trip token is still returned and still used.
- `GET /trips/{id}/buffer`: the playlist covers the camera's whole loop, including footage from before the trip started. `playlist_url` and every segment URL inside the playlist carry a short-lived signed query string (for example `?exp=<unix>&sig=<hmac>`), issued after the trip token check. This works with Safari's native HLS and with hls.js without custom headers. The client treats the URL as opaque and adds no headers. When playback fails with 401/403, the signature has expired: call this endpoint again for a fresh URL.
- `POST /trips/{id}/incidents` works signed out. The server stamps `trigger_at` on receipt, preserves pre-trigger segments, and starts post-trigger recording before responding. Signed out, the response has `claim_state: "unclaimed"` and an `expires_at` about 15 minutes later. Signed in, it is `"claimed"` immediately.
- Ending a trip deletes nothing. The camera's loop keeps rolling.

### Signed in

All require `Authorization`. Missing or invalid token returns 401.

| Method and path | Extra headers | Returns |
| --- | --- | --- |
| `GET /me` | none | `User` |
| `POST /incidents/{incident_id}/claim` | `X-Trip-Token` of the incident's trip | `Incident` |
| `GET /incidents` | none | `Incident[]`, caller's only, newest `trigger_at` first |
| `GET /incidents/{incident_id}` | none | `Incident` |
| `GET /incidents/{incident_id}/playback` | none | `Playback` |
| `DELETE /incidents/{incident_id}` | none | `204 No Content` |

- **Claim:** succeeds only with a valid access token plus the right trip token. First claim wins: a second claim returns 409, an expired one returns 410.
- **List:** metadata only. The list page must not request playback for every row. It may load each row's `thumbnail_url`: a small image, not the clip. The link is relative to the API origin, signed, and valid for 5 to 10 minutes; load it as-is.
- **Poll** `GET /incidents/{id}` every 2 to 3 seconds while `processing_state` is not `ready` or `failed`. No websockets for now.
- **Delete** removes the stored clip and the incident row. Only the owner can delete; anyone else gets 404. Client clears that incident's cached playback URL. Deleting an incident that is still `recording` cancels it: recording stops and the footage kept so far is released. While it is `assembling`, delete returns 409; try again once it is `ready` or `failed`.
- **Automatic deletion:** a saved clip is deleted by the server at `deletes_at`, 30 days after the press (a server setting, `SAVED_CLIP_SECONDS`). It then drops out of the list, and `GET /incidents/{id}` returns 404. The client shows the time left from `deletes_at` and never assumes the period.
- **Playback** returns 409 until `processing_state` is `ready`. Cache the result per (user id, incident id, `video_version`) until shortly before `expires_at`; clear that cache on sign-out and account switch.

## The incident flow, signed out

This is the demo path, so both sides should test it end to end.

1. `POST /trips` returns `trip_token`. Client saves it in `sessionStorage` keyed by trip id.
2. User presses **I was in an incident**: `POST /trips/{id}/incidents` with `X-Trip-Token`. Response is `unclaimed`.
3. Client saves `{ incident_id, trip_id }` as the pending incident in `sessionStorage`, then starts Google sign-in. The Supabase redirect leaves the tab, so anything only in React state is lost; `sessionStorage` survives within the same tab.
4. Back from sign-in, client reads the pending incident and calls `POST /incidents/{id}/claim` with both headers, then clears the pending entry.
5. Client polls `GET /incidents/{id}` until `ready`, then shows it in **Saved Incidents**.

## Mock vs real backend

The frontend talks to the backend only through one API module that exposes one function per endpoint above. It has two implementations behind the same interface:

- **mock**: in-memory, adds ~250 ms latency, and enforces the same rules as the server (trip token checks, 401 when signed out, first claim wins, ownership on list and playback, 409 until ready). Processing moves through `recording`, `assembling`, `ready` on a short timer. Uses public sample video URLs as placeholders, clearly labeled as mock. Sign-in is faked instantly with no redirect.
- **http**: `fetch` against `/api`, with real Supabase Google sign-in.

Selected by one env var in `client/.env.local`:

```
VITE_API_MODE=mock   # or http
```

Default is `mock` until the backend endpoints exist. Components import only the shared API module, never `fetch` directly, so switching changes no UI code. On the server side, the Pydantic response models should mirror the types above so FastAPI's `/docs` page can be checked against this file.

## Decisions

- **Status updates:** polling every 2 to 3 seconds, no SSE or websockets.
- **Buffer playlist auth:** signed query string on the playlist and segment URLs.
- **Clip windows:** 60 s before the press, 15 s after by default. These are server settings (for example `PRE_TRIGGER_SECONDS=60`, `POST_TRIGGER_SECONDS=15`); the client only displays what `Incident` returns.
- **Saved Incidents shows:** camera source timestamps, duration and file size, SHA-256, and a delete action.
