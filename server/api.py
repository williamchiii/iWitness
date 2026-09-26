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

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse

try:
    from . import db
    from .config import SERVER_ROOT, settings
    from .schemas import (
        BufferInfoResponse,
        CameraResponse,
        StartTripRequest,
        StartTripResponse,
        TripResponse,
    )
except ImportError:
    # Supports ``uvicorn main:app`` when launched from the server directory.
    import db
    from config import SERVER_ROOT, settings
    from schemas import (
        BufferInfoResponse,
        CameraResponse,
        StartTripRequest,
        StartTripResponse,
        TripResponse,
    )


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


def _load_trip(trip_id: UUID, trip_token: str) -> TripResponse:
    with db.connect() as connection:
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


def _signature(payload: str, expires: int) -> str:
    message = f"{payload}|{expires}".encode("utf-8")
    return hmac.new(
        settings.playback_signing_secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def _verify_signature(payload: str, expires: int, signature: str) -> None:
    if expires <= int(time.time()):
        raise HTTPException(status_code=403, detail="Playback URL expired")
    expected = _signature(payload, expires)
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=403, detail="Invalid playback signature")


def _safe_media_path(file_path: str) -> Path:
    candidate = (SERVER_ROOT / file_path).resolve()
    try:
        candidate.relative_to(settings.media_root.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Segment not found") from exc
    return candidate


@router.get("/cameras", response_model=list[CameraResponse])
def list_cameras() -> list[CameraResponse]:
    with db.connect() as connection:
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
def start_trip(request: StartTripRequest) -> StartTripResponse:
    with db.connect() as connection:
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
) -> TripResponse:
    if not x_trip_token:
        raise HTTPException(status_code=403, detail="Trip token required")

    trip = _load_trip(trip_id, x_trip_token)
    if trip.state == "ended":
        return trip

    with db.connect() as connection:
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
) -> BufferInfoResponse:
    if not x_trip_token:
        raise HTTPException(status_code=403, detail="Trip token required")

    trip = _load_trip(trip_id, x_trip_token)
    with db.connect() as connection:
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
    signature = _signature(payload, expires)
    query = urlencode({"trip_id": str(trip_id), "exp": expires, "sig": signature})
    playlist_path = f"/playback/buffer/{trip.camera_id}/playlist.m3u8?{query}"
    playlist_url = str(request.base_url).rstrip("/") + playlist_path

    return BufferInfoResponse(
        camera_id=trip.camera_id,
        playlist_url=playlist_url,
        earliest=earliest,
        latest=latest,
    )


@router.get(
    "/playback/buffer/{camera_id}/playlist.m3u8",
    response_class=PlainTextResponse,
)
def buffer_playlist(
    camera_id: str,
    trip_id: UUID = Query(...),
    exp: int = Query(...),
    sig: str = Query(...),
) -> PlainTextResponse:
    _verify_signature(f"playlist|{trip_id}|{camera_id}", exp, sig)

    with db.connect() as connection:
        trip = connection.execute(
            "SELECT camera_id FROM trip WHERE id = %s",
            (trip_id,),
        ).fetchone()
        if trip is None or trip[0] != camera_id:
            raise HTTPException(status_code=404, detail="Buffer not found")

        rows = connection.execute(
            """
            SELECT id, file_path, actual_start, actual_end
            FROM segment
            WHERE camera_id = %s
              AND status IN ('temporary', 'preserved')
            ORDER BY actual_start ASC
            """,
            (camera_id,),
        ).fetchall()

    segments: list[tuple[UUID, datetime, datetime]] = []
    for segment_id, file_path, actual_start, actual_end in rows:
        path = _safe_media_path(file_path)
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
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{target_duration}",
        "#EXT-X-MEDIA-SEQUENCE:0",
    ]
    for segment_id, actual_start, actual_end in segments:
        expires = int(time.time()) + settings.playback_url_seconds
        segment_signature = _signature(
            f"segment|{segment_id}|{camera_id}",
            expires,
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
) -> FileResponse:
    _verify_signature(f"segment|{segment_id}|{camera_id}", exp, sig)

    with db.connect() as connection:
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

    path = _safe_media_path(row[0])
    if not path.is_file() or path.stat().st_size == 0:
        raise HTTPException(status_code=404, detail="Segment not found")

    return FileResponse(
        path,
        media_type="video/mp2t",
        headers={"Cache-Control": "private, max-age=300"},
    )
