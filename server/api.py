"""Anonymous camera, trip, and authorized buffer playback endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import math
from pathlib import Path
import secrets
import time
from urllib.parse import urlencode
from uuid import UUID

import psycopg

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse

from . import db
from .auth import Principal, get_optional_principal
from .config import SERVER_ROOT, Settings, get_settings
from .schemas import (
    BufferInfoResponse,
    CameraResponse,
    StartTripRequest,
    StartTripResponse,
    TripResponse,
)
from .incident_schemas import IncidentResponse
from .segment_preservation import preserve_segments


router = APIRouter()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _trip_from_row(row: tuple[object, ...]) -> TripResponse:
    return TripResponse(
        id=str(row[0]),
        camera_id=str(row[1]),
        started_at=_utc(row[2]),
        ended_at=_utc(row[3]) if row[3] is not None else None,
        state=str(row[4]),
    )


def _incident_from_row(row: tuple[object, ...]) -> IncidentResponse:
    """Convert the incident query shape into the public response model."""

    return IncidentResponse(
        id=str(row[0]),
        trip_id=str(row[1]),
        camera_id=str(row[2]),
        camera_name=str(row[3]),
        source_type=str(row[4]),
        trigger_at=_utc(row[5]),
        requested_start=_utc(row[6]),
        requested_end=_utc(row[7]),
        actual_start=_utc(row[8]) if row[8] is not None else None,
        actual_end=_utc(row[9]) if row[9] is not None else None,
        source_start=_utc(row[10]) if row[10] is not None else None,
        source_end=_utc(row[11]) if row[11] is not None else None,
        duration_seconds=row[12],
        size_bytes=row[13],
        sha256=row[14],
        processing_state=str(row[15]),
        claim_state=str(row[16]),
        expires_at=_utc(row[17]) if row[17] is not None else None,
        video_version=row[18],
        error=row[19],
    )


_INCIDENT_SELECT = """
    SELECT i.id, i.trip_id, i.camera_id, c.name, c.source_type,
           i.trigger_at, i.requested_start, i.requested_end,
           i.actual_start, i.actual_end, i.source_start, i.source_end,
           i.duration_seconds, i.size_bytes, i.sha256,
           i.processing_state, i.claim_state, i.expires_at,
           i.video_version, i.error
    FROM incident AS i
    JOIN camera AS c ON c.id = i.camera_id
    WHERE i.id = %s
"""


def _load_trip(trip_id: UUID, trip_token: str, connection: psycopg.Connection) -> TripResponse:
    row = connection.execute(
        """
        SELECT id, camera_id, started_at, ended_at, state, anonymous_token_hash
        FROM trip
        WHERE id = %s
        """,
        (trip_id,),
    ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    if not hmac.compare_digest(row[5], _token_hash(trip_token)):
        raise HTTPException(status_code=403, detail="Invalid trip token")
    return _trip_from_row(row)


def _signature(payload: str, expires: int, settings: Settings) -> str:
    message = f"{payload}|{expires}".encode("utf-8")
    return hmac.new(
        settings.playback_signing_secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def _verify_signature(payload: str, expires: int, signature: str, settings: Settings) -> None:
    if expires <= int(time.time()):
        raise HTTPException(status_code=403, detail="Playback URL expired")
    expected = _signature(payload, expires, settings)
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=403, detail="Invalid playback signature")


def _safe_media_path(file_path: str, settings: Settings) -> Path:
    candidate = (SERVER_ROOT / file_path).resolve()
    try:
        candidate.relative_to(settings.media_root.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Segment not found") from exc
    return candidate


@router.get("/cameras", response_model=list[CameraResponse])
def list_cameras(connection: psycopg.Connection = Depends(db.get_db)) -> list[CameraResponse]:
    """List permitted cameras, newest recorder state included."""

    rows = connection.execute(
        """
        SELECT id, name, location, source_type, recording
        FROM camera
        WHERE permitted = TRUE
        ORDER BY id
        """
    ).fetchall()

    return [
        CameraResponse(
            id=row[0],
            name=row[1],
            location=row[2],
            source_type=row[3],
            recording=row[4],
        )
        for row in rows
    ]


@router.post("/trips", response_model=StartTripResponse)
def start_trip(request: StartTripRequest, connection: psycopg.Connection = Depends(db.get_db)) -> StartTripResponse:
    """Start an anonymous trip on a permitted camera and issue its token."""

    camera = connection.execute(
        """
        SELECT id
        FROM camera
        WHERE id = %s AND permitted = TRUE
        """,
        (request.camera_id,),
    ).fetchone()
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")

    trip_token = secrets.token_urlsafe(32)
    row = connection.execute(
        """
        INSERT INTO trip (camera_id, anonymous_token_hash)
        VALUES (%s, %s)
        RETURNING id, camera_id, started_at, ended_at, state
        """,
        (request.camera_id, _token_hash(trip_token)),
    ).fetchone()

    return StartTripResponse(
        trip=_trip_from_row(row),
        trip_token=trip_token,
    )


@router.post("/trips/{trip_id}/end", response_model=TripResponse)
def end_trip(
    trip_id: UUID,
    x_trip_token: str | None = Header(default=None, alias="X-Trip-Token"),
    connection: psycopg.Connection = Depends(db.get_db),
) -> TripResponse:
    """End a trip. The camera's loop buffer keeps recording regardless."""

    if not x_trip_token:
        raise HTTPException(status_code=403, detail="Trip token required")

    trip = _load_trip(trip_id, x_trip_token, connection)
    if trip.state == "ended":
        return trip

    row = connection.execute(
        """
        UPDATE trip
        SET state = 'ended', ended_at = now()
        WHERE id = %s
        RETURNING id, camera_id, started_at, ended_at, state
        """,
        (trip_id,),
    ).fetchone()
    return _trip_from_row(row)


@router.get("/trips/{trip_id}/buffer", response_model=BufferInfoResponse)
def get_buffer(
    trip_id: UUID,
    request: Request,
    x_trip_token: str | None = Header(default=None, alias="X-Trip-Token"),
    connection: psycopg.Connection = Depends(db.get_db),
    settings: Settings = Depends(get_settings),
) -> BufferInfoResponse:
    """Return the camera's current loop window and a signed playlist URL."""

    if not x_trip_token:
        raise HTTPException(status_code=403, detail="Trip token required")

    trip = _load_trip(trip_id, x_trip_token, connection)
    row = connection.execute(
        """
        SELECT min(actual_start), max(actual_end)
        FROM segment
        WHERE camera_id = %s
          AND status IN ('temporary', 'preserved')
        """,
        (trip.camera_id,),
    ).fetchone()

    earliest = _utc(row[0]) if row[0] is not None else None
    latest = _utc(row[1]) if row[1] is not None else None
    expires = int(time.time()) + settings.playback_url_seconds
    payload = f"playlist|{trip_id}|{trip.camera_id}"
    signature = _signature(payload, expires, settings)
    query = urlencode({"trip_id": str(trip_id), "exp": expires, "sig": signature})
    playlist_path = f"/playback/buffer/{trip.camera_id}/playlist.m3u8?{query}"
    playlist_url = str(request.base_url).rstrip("/") + playlist_path

    return BufferInfoResponse(
        camera_id=trip.camera_id,
        playlist_url=playlist_url,
        earliest=earliest,
        latest=latest,
    )


@router.post(
    "/trips/{trip_id}/incidents",
    response_model=IncidentResponse,
    status_code=201,
)
def create_incident(
    trip_id: UUID,
    x_trip_token: str | None = Header(default=None, alias="X-Trip-Token"),
    principal: Principal | None = Depends(get_optional_principal),
    connection: psycopg.Connection = Depends(db.get_db),
    settings: Settings = Depends(get_settings),
) -> IncidentResponse:
    """Create an incident and preserve footage already in its time window."""

    if not x_trip_token:
        raise HTTPException(status_code=403, detail="Trip token required")

    trip = _load_trip(trip_id, x_trip_token, connection)
    user_id: UUID | None = None
    if principal is not None:
        try:
            user_id = UUID(principal.id)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=401, detail="Authenticated user id is invalid") from exc
        if not principal.email:
            raise HTTPException(status_code=401, detail="Authenticated user email is missing")

    if principal is not None:
        connection.execute(
            """
            INSERT INTO app_user (id, email, display_name, avatar_url)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                email = EXCLUDED.email,
                display_name = COALESCE(EXCLUDED.display_name, app_user.display_name),
                avatar_url = COALESCE(EXCLUDED.avatar_url, app_user.avatar_url)
            """,
            (user_id, principal.email, principal.display_name, principal.avatar_url),
        )
    inserted = connection.execute(
        """
        INSERT INTO incident (
            trip_id,
            camera_id,
            user_id,
            trigger_at,
            requested_start,
            requested_end,
            processing_state,
            claim_state,
            expires_at
        )
        VALUES (
            %s,
            %s,
            %s,
            now(),
            now() - (%s * interval '1 second'),
            now() + (%s * interval '1 second'),
            'recording',
            CASE WHEN %s::uuid IS NULL THEN 'unclaimed' ELSE 'claimed' END,
            CASE WHEN %s::uuid IS NULL THEN now() + (%s * interval '1 second') ELSE NULL END
        )
        RETURNING id, requested_start, trigger_at
        """,
        (
            trip_id,
            trip.camera_id,
            user_id,
            settings.pre_trigger_seconds,
            settings.post_trigger_seconds,
            user_id,
            user_id,
            settings.unclaimed_incident_seconds,
        ),
    ).fetchone()
    incident_id, requested_start, trigger_at = inserted

    preserve_segments(
        connection,
        incident_id,
        trip.camera_id,
        requested_start,
        trigger_at,
    )

    row = connection.execute(_INCIDENT_SELECT, (incident_id,)).fetchone()

    if row is None:
        # The insert succeeded, so reaching this branch indicates a database
        # inconsistency rather than a client error.
        raise HTTPException(status_code=500, detail="Incident could not be loaded")
    return _incident_from_row(row)


@router.get(
    "/playback/buffer/{camera_id}/playlist.m3u8",
    response_class=PlainTextResponse,
)
def buffer_playlist(
    camera_id: str,
    trip_id: UUID = Query(...),
    exp: int = Query(...),
    sig: str = Query(...),
    connection: psycopg.Connection = Depends(db.get_db),
    settings: Settings = Depends(get_settings),
) -> PlainTextResponse:
    """Build an HLS playlist covering the camera's whole current loop."""

    _verify_signature(f"playlist|{trip_id}|{camera_id}", exp, sig, settings)

    trip = connection.execute(
        "SELECT camera_id, started_at FROM trip WHERE id = %s",
        (trip_id,),
    ).fetchone()
    if trip is None or trip[0] != camera_id:
        raise HTTPException(status_code=404, detail="Buffer not found")

    rows = connection.execute(
        """
        SELECT id, file_path, actual_start, actual_end, status
        FROM segment
        WHERE camera_id = %s
          AND status IN ('temporary', 'preserved')
        ORDER BY actual_start ASC
        """,
        (camera_id,),
    ).fetchall()

    # Segments preserved for an incident outlive the loop. Listing ones older
    # than the loop would leave a gap that renumbers every later segment as
    # the loop rolls forward, so start at the oldest temporary segment.
    loop_start = min(
        (row[2] for row in rows if row[4] == "temporary"),
        default=None,
    )

    segments: list[tuple[UUID, datetime, datetime]] = []
    for segment_id, file_path, actual_start, actual_end, _status in rows:
        if loop_start is not None and actual_start < loop_start:
            continue
        path = _safe_media_path(file_path, settings)
        if not path.is_file() or path.stat().st_size == 0:
            continue
        segments.append((segment_id, _utc(actual_start), _utc(actual_end)))

    target_duration = max(
        [
            1,
            *[
                math.ceil((actual_end - actual_start).total_seconds())
                for _, actual_start, actual_end in segments
            ],
        ]
    )
    # No #EXT-X-PLAYLIST-TYPE tag: this is a fresh snapshot of the current
    # loop buffer on every request, not an append-only EVENT playlist —
    # retention removes the oldest segments as the loop rolls forward.
    # Players match segments across reloads by sequence number, so number
    # each one by its start time: it keeps its number as older ones drop off.
    # Count from a day before the oldest footage the loop could hold when this
    # trip began, not from 1970: hls.js keeps per-discontinuity state in
    # arrays indexed by that number, and a huge one makes every segment take
    # seconds to load. The spare day keeps the first number above zero even
    # when retention runs late.
    numbering_origin = _utc(trip[1]).timestamp() - (
        settings.buffer_seconds + settings.playback_url_seconds + 86_400
    )
    first_number = (
        max(
            0,
            math.floor(
                (segments[0][1].timestamp() - numbering_origin)
                / settings.segment_seconds
            ),
        )
        if segments
        else 0
    )
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{target_duration}",
        f"#EXT-X-MEDIA-SEQUENCE:{first_number}",
        # One discontinuity per segment (see below), so the same numbering.
        f"#EXT-X-DISCONTINUITY-SEQUENCE:{first_number}",
    ]
    for index, (segment_id, actual_start, actual_end) in enumerate(segments):
        # The recorder cuts with -reset_timestamps, so every segment's
        # timestamps restart near zero. Without a discontinuity, a player that
        # jumps back places the segment at the wrong time and snaps to live.
        if index > 0:
            lines.append("#EXT-X-DISCONTINUITY")
        expires = int(time.time()) + settings.playback_url_seconds
        segment_signature = _signature(
            f"segment|{segment_id}|{camera_id}",
            expires,
            settings,
        )
        query = urlencode({
            "camera_id": camera_id,
            "exp": expires,
            "sig": segment_signature,
        })
        duration = max(0.001, (actual_end - actual_start).total_seconds())
        timestamp = actual_start.isoformat().replace("+00:00", "Z")
        lines.extend(
            [
                f"#EXT-X-PROGRAM-DATE-TIME:{timestamp}",
                f"#EXTINF:{duration:.3f},",
                f"/playback/segments/{segment_id}?{query}",
            ]
        )

    return PlainTextResponse(
        "\n".join(lines) + "\n",
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "private, max-age=5"},
    )


@router.get("/playback/segments/{segment_id}")
def playback_segment(
    segment_id: UUID,
    camera_id: str = Query(...),
    exp: int = Query(...),
    sig: str = Query(...),
    connection: psycopg.Connection = Depends(db.get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Serve one segment file behind its own short-lived signed URL."""

    _verify_signature(f"segment|{segment_id}|{camera_id}", exp, sig, settings)

    row = connection.execute(
        """
        SELECT file_path
        FROM segment
        WHERE id = %s AND camera_id = %s
        """,
        (segment_id, camera_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Segment not found")

    path = _safe_media_path(row[0], settings)
    if not path.is_file() or path.stat().st_size == 0:
        raise HTTPException(status_code=404, detail="Segment not found")

    return FileResponse(
        path,
        media_type="video/mp2t",
        headers={"Cache-Control": "private, max-age=300"},
    )
