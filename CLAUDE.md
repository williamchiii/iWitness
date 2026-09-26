# iWitness — ShellHacks 2026 (State Farm Auto Insurance track)

Full brief: [docs/project_brief.md](docs/project_brief.md). Read it before any design decision; this file is the short version.

**One sentence:** A student starts a trip (no sign-in needed), picks one of five permitted FDOT cameras on I-95 in Miami-Dade County, the backend keeps a dashcam-style 5-hour loop recording of each camera that the user can scrub back through, and pressing **I was in an incident** saves a clip (including footage from *before* the press) to their private account, signing in with Google at that point if they have not already.

## The goal: one convincing live moment

A judge presses the incident button and immediately watches video from before the press. Everything we build serves that ~75 second demo:

1. Open the app signed out, pick one of the five I-95 cameras, start a trip, video plays.
2. Scrub the player back to show the buffer holds footage older than "now".
3. Press **I was in an incident**: earlier segments are kept immediately, post-trigger recording starts, and the app prompts Google sign-in to save.
4. After sign-in, **Saved Incidents** shows the block (camera name, source, actual recording window, trigger time). Play it, scrub to before the press.
5. Sign out, sign back in: block is still there, plays and downloads.

Working code + clear story + rehearsed demo beats clever code. Protect the demo over adding features.

## Build order (do not skip ahead)

1. Record one permitted I-95 camera to a fresh 30 s file and play it back. **First gate; solve before frontend work.**
2. Short segments (~10 s) in a 5-hour loop buffer per camera that overwrites the oldest, all five cameras running, plus scrub-back playback of the buffer.
3. Incident trigger preserves earlier segments (works signed out).
4. Google sign in at save time; attach the pending incident to the verified user.
5. Post-trigger recording, clip assembly, private storage, playback, download.
6. Trip UI (camera list) and Saved Incidents page with accurate time labels.
7. Recently-viewed playback cache, cleared on sign out.
8. Rehearse on the judging laptop with a local replay fallback.

## Deliberate cuts — do not build unless asked

More than the five chosen I-95 cameras, statewide coverage, route matching, maps (the camera picker is a plain list), background location, computer vision, crash/wet-road detection, fault estimation, claims chatbot, State Farm submission, PDF reports, payments, cryptographic chain of custody. If a task drifts toward these, stop and ask.

## Stack and layout

- `client/` — React 19 + TypeScript + Vite 8, linted with oxlint. Vite proxies `/api/*` to `http://localhost:8000` and **strips the `/api` prefix** (so client `fetch('/api/health')` hits backend `/health`).
- `server/` — FastAPI (Python 3.14) in `server/.venv`. Entry `server/main.py`. No `requirements.txt` yet; add one when adding dependencies.
- Recording: FFmpeg (installed locally), one process per camera. Planned: Supabase Auth (Google), Postgres, private Storage.
- `docs/project_brief.md` — source of truth for scope, data model, and claims.

## Commands

```bash
# client
cd client && npm install && npm run dev      # http://localhost:5173
cd client && npm run build                   # tsc -b + vite build
cd client && npm run lint                    # oxlint

# server
cd server && source .venv/bin/activate
uvicorn main:app --reload --port 8000        # or: fastapi dev main.py
ruff check .                                 # pip install ruff; config in server/ruff.toml
```

CI (`.github/workflows/ci.yml`, GitHub Actions) runs on push to `main` and on PRs: client `npm ci` + lint + build; server `ruff check` + start uvicorn against a throwaway Postgres service and `POST /health`. Keep both green.

## Auth model: watch anonymously, sign in to save

- **No sign-in needed** to open the app, start a trip, watch the live camera, scrub back through the loop buffer, or have it record.
- **Sign-in is required only to save**: pressing **I was in an incident** when signed out must not lose footage. Record the trigger time at the press, mark the earlier segments preserved and start post-trigger recording right away, *then* prompt Google sign-in.
- Anonymous trips get an unguessable server-issued trip token held by that browser. After sign-in, the backend attaches the pending incident to the verified user only if the request carries that token plus a valid auth token. The first claim wins; a claimed incident cannot be claimed again.
- Unclaimed pending incidents expire (for example 15 minutes after the press) and their preserved video is deleted. Loop buffers belong to cameras, not trips, so ending a trip deletes nothing; the loop keeps rolling.
- **Saved Incidents is always private**: listing, playback, and download of saved clips require sign-in and ownership. "View without signing in" means the live trip stream only, never another user's saved clips.

## Loop buffer: 5 hours, dashcam style

- **Buffer per camera, always on.** One FFmpeg per permitted camera writes ~10 s segments whenever the server runs, trip or not. A trip is a pointer to (camera, time range); students on the same camera share one buffer. A trip may scrub the camera's whole loop, including footage from before the trip started.
- Retention is a **5-hour loop**: once the buffer is full, the oldest *temporary* segment is deleted as each new one is written. Preserved segments (part of an incident) are never overwritten.
- Make retention a setting (for example `BUFFER_SECONDS=18000`) so the demo and tests can run with a few minutes without code changes.
- **Playback of the buffer:** the player can scrub back through everything currently in the loop, not just the live edge. Serve our own HLS playlist built from `segment` rows. **Do not use FFmpeg `-hls_flags delete_segments`**: it deletes by position and cannot skip preserved segments. Only a request with a valid trip token or the trip's signed-in owner may fetch a playlist.
- **Incident clip size is separate from buffer size.** Pressing the button preserves a pre-trigger window (default a few minutes, configurable) plus the post-trigger window, not the whole 5 hours. The rest of the loop keeps overwriting as normal.
- **Disk budget:** 5 hours is about 2.25 GB per camera at 1 Mbps, so ~11 GB for five cameras and ~5 Mbps steady ingest. Record at a modest bitrate/resolution (for example 720p, ~1 Mbps, or `-c copy` if the source is already small), and also delete oldest temporary segments if free disk drops below a floor. Log when that happens.
- Segment deletion must be driven by recorded time, not wall clock guesses, so gaps in the source do not silently shrink or stretch the window.

## Where data lives

| Data | Storage | Path / table |
| --- | --- | --- |
| Loop buffer segments | Local SSD | `media/cameras/<camera_id>/<epoch_seconds>.ts` |
| Clip being assembled | Local SSD | `media/incidents/<incident_id>/clip.mp4` (`ffmpeg -f concat -c copy -movflags +faststart`) |
| Saved clips | Supabase Storage, private bucket | `incidents/<user_id>/<incident_id>/v<version>.mp4` |
| Metadata | Supabase Postgres | `camera`, `user`, `trip`, `segment`, `incident` |
| Signed playback URLs | Browser memory | client LRU |

After upload, delete the local preserved segments and `clip.mp4`. Never serve `media/` as public static files. Offline fallback: `incident.storage_path` may point to a local file served by an authenticated FastAPI endpoint with the same ownership check and response shape.

## Security rules (non-negotiable)

- Frontend sends the auth token; backend verifies it and derives the user ID. **Never trust a user ID from the request body or query.**
- Every incident list, playback, and download checks ownership. Another account must not list or fetch them.
- Storage buckets stay private. Use short-lived signed URLs or an authenticated backend response.
- Never commit OAuth credentials, Supabase service keys, or `.env` files. Service keys stay server-side only.

## Recording and clip rules

- Output must be **real, newly recorded video**, never a prebuilt clip revealed after the press and never stills presented as video (label snapshot sources a time lapse).
- Replayed demo input must go through the **same recording pipeline** and be labeled as replayed.
- Store both the source's own timestamp and the server's recording time; keep them separate. Show the *actual* clip start/end, not the requested window.
- Critical test: the saved clip contains a visible clock or event from before the button press.
- The judged demo must work without an unstable external network feed.

## Data model (suggested)

- `camera`: id, name, location (I-95 mile marker / cross street), source type, input URL, permission status
- `user`: Google user id, display info
- `trip`: id, **user_id (nullable while anonymous)**, anonymous trip token hash, camera_id, start, end, state
- `segment`: **camera_id**, file path, source timestamp, actual start/end, temporary or preserved, incident_id when preserved
- `incident`: id, **user_id (null until claimed)**, trip_id, camera_id, trigger time, requested window, actual window, private video path, video version, processing state, claim state, expires_at

## Recently-viewed playback cache (client)

Small in-memory LRU keyed by **(user_id, incident_id, video_version)**, holding the signed playback URL until shortly before expiry. Reusing the same URL lets the browser's HTTP cache reuse video bytes. Clear on sign out, account switch, clip deletion, and video replacement. Player loads metadata first, streams on play; the list page must not download every clip. Never share a server-side byte cache across users.

## Data rights and honest claims

- The team has **FDOT's written permission** to record the five chosen I-95 cameras. Record only cameras that permission covers; the recorder refuses any `camera` not marked permitted. Permission details (grantor, date, camera list) are in `CLAUDE.local.md`, not in git.
- The ArcGIS `FL511_Traffic_Cameras` layer is metadata. Use it to find cameras, then confirm each streams continuous video (not periodic stills) before choosing it.
- In UI copy and pitch text: a clip may not show the student's car; it provides context, not proof of fault; a file hash shows our file is unchanged, not what happened on the road; describe FDOT access exactly as the permission states it, never as a partnership unless it is one.

## Team split

| Person | Owns |
| --- | --- |
| One | Video input for the five cameras, segment recording, 5-hour loop retention, buffer playlist |
| Two | Auth, trip ownership, incident state, private storage, playback/download endpoints |
| Three | Sign-in, trip screen, Saved Incidents page, playback cache, pitch and rehearsal |

Agree on file paths and API response shapes before building across the boundary.

## Repo gotchas

- Root `.gitignore` has `*.ts` (meant for MPEG-TS video segments), which also ignores TypeScript files such as `client/vite.config.ts`. Check `git check-ignore -v <file>` before assuming a `.ts` file is tracked; prefer a narrower pattern (for example `segments/**/*.ts`) if this bites.
- Recorded media (`recordings/`, `segments/`, `media/`, `*.mp4`, `*.m3u8`) is gitignored. Keep video out of git.
- `/health` is currently `POST`, not `GET`.

## Working style for agents

- Smallest change that moves the demo forward. No speculative abstractions, no features from the cut list.
- Machine- or person-specific notes (camera stream URLs, permission details, local paths) go in `CLAUDE.local.md`, which is gitignored.
- Match existing code style; keep the client simple (plain React state until something forces more).
- After backend changes, verify with a real request; after recording changes, verify by playing the output file.
