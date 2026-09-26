"""Private playback and deletion endpoints for saved incidents."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import urlencode
from uuid import UUID

import psycopg

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from . import db
from .auth import Principal, get_current_principal
from .config import SERVER_ROOT, Settings, get_settings


router = APIRouter()

# A still from each ready clip for the Library, made on first request and kept
# next to the clip.
THUMBNAIL_NAME = "thumbnail.jpg"
THUMBNAIL_WIDTH = 480


class PlaybackResponse(BaseModel):
    """Short-lived URLs for an owned, ready incident clip."""

    incident_id: str
    video_version: int
    playback_url: str
    download_url: str
    expires_at: datetime


def _signature(payload: str, expires: int, settings: Settings) -> str:
    """Sign a playback URL payload with the configured server secret."""

    message = f"{payload}|{expires}".encode("utf-8")
    return hmac.new(
        settings.playback_signing_secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def _verify_signature(payload: str, expires: int, signature: str, settings: Settings) -> None:
    """Reject expired or forged local playback URLs."""

    if expires <= int(time.time()):
        raise HTTPException(status_code=403, detail="Playback URL expired")
    expected = _signature(payload, expires, settings)
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=403, detail="Invalid playback signature")


def _incident_directory(incident_id: UUID, settings: Settings) -> Path:
    """Return the incident's validated local media directory."""

    root = settings.incidents_root.resolve()
    directory = (root / str(incident_id)).resolve()
    try:
        directory.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Incident clip not found") from exc
    return directory


def _safe_clip_path(
    incident_id: UUID,
    storage_path: str | None,
    settings: Settings,
    *,
    require_file: bool,
) -> Path | None:
    """Resolve a stored clip only inside its incident-specific directory."""

    if not storage_path:
        if require_file:
            raise HTTPException(status_code=404, detail="Incident clip not found")
        return None

    directory = _incident_directory(incident_id, settings)
    configured = Path(storage_path)
    candidate = (
        configured if configured.is_absolute() else SERVER_ROOT / configured
    ).resolve()
    try:
        candidate.relative_to(directory)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Incident clip not found") from exc

    if candidate == directory:
        raise HTTPException(status_code=404, detail="Incident clip not found")
    if require_file:
        try:
            if not candidate.is_file() or candidate.stat().st_size == 0:
                raise HTTPException(status_code=404, detail="Incident clip not found")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Incident clip not found") from exc
    elif candidate.exists() and not candidate.is_file():
        raise HTTPException(status_code=500, detail="Incident clip path is invalid")
    return candidate


def _signed_clip_url(
    request: Request,
    incident_id: UUID,
    user_id: str,
    expires: int,
    settings: Settings,
    *,
    download: bool,
) -> str:
    """Build a signed URL that can be used without an Authorization header."""

    action = "download" if download else "playback"
    signature = _signature(
        f"incident|{incident_id}|{user_id}|{action}",
        expires,
        settings,
    )
    query = urlencode(
        {
            "uid": user_id,
            "exp": expires,
            "sig": signature,
            "download": "1" if download else "0",
        }
    )
    path = f"/playback/incidents/{incident_id}?{query}"
    return str(request.base_url).rstrip("/") + path


def signed_thumbnail_url(
    incident_id: UUID | str,
    user_id: str,
    settings: Settings | None = None,
) -> str:
    """Return a short-lived link to a ready clip's still that only its owner can use.

    The expiry is rounded up to a whole window, so every list within a window
    gets the same link and the browser reuses its cached image. The link is
    valid for one to two windows.
    """

    settings = settings or get_settings()
    window = settings.playback_url_seconds
    expires = (int(time.time()) // window + 2) * window
    signature = _signature(
        f"incident|{incident_id}|{user_id}|thumbnail",
        expires,
        settings,
    )
    query = urlencode({"uid": user_id, "exp": expires, "sig": signature})
    # Relative: the browser loads it from the same origin as the API.
    return f"/playback/incidents/{incident_id}/thumbnail?{query}"


def _thumbnail_offset(
    trigger_at: datetime | None,
    actual_start: datetime | None,
    duration_seconds: float | None,
) -> float:
    """Seconds into the clip to take the still: the press, else the middle."""

    if trigger_at is not None and actual_start is not None:
        offset = (trigger_at - actual_start).total_seconds()
    else:
        offset = (duration_seconds or 0) / 2
    if duration_seconds:
        offset = min(offset, max(duration_seconds - 0.5, 0))
    return max(offset, 0.0)


def _make_thumbnail(clip: Path, thumbnail: Path, offset: float, settings: Settings) -> None:
    """Save one scaled JPEG frame of ``clip`` as ``thumbnail``."""

    # A unique temporary name, so two first requests can't write one file.
    with tempfile.NamedTemporaryFile(
        dir=thumbnail.parent, prefix="thumbnail.", suffix=".jpg", delete=False
    ) as handle:
        partial = Path(handle.name)
    try:
        subprocess.run(
            [
                settings.ffmpeg_binary,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{offset:.3f}",
                "-i",
                str(clip),
                "-frames:v",
                "1",
                "-vf",
                f"scale={THUMBNAIL_WIDTH}:-2",
                "-q:v",
                "4",
                str(partial),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
            timeout=20,
        )
        if partial.stat().st_size == 0:
            raise OSError("FFmpeg wrote an empty thumbnail")
        partial.replace(thumbnail)
    except (OSError, subprocess.SubprocessError) as exc:
        partial.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail="Incident thumbnail could not be made",
        ) from exc


@router.get(
    "/incidents/{incident_id}/playback",
    response_model=PlaybackResponse,
)
def get_incident_playback(
    incident_id: UUID,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    connection: psycopg.Connection = Depends(db.get_db),
    settings: Settings = Depends(get_settings),
) -> PlaybackResponse:
    """Issue signed playback and download URLs for an owned ready clip."""

    row = connection.execute(
        """
        SELECT storage_path, processing_state, video_version
        FROM incident
        WHERE id = %s AND user_id = %s
        """,
        (incident_id, principal.id),
    ).fetchone()

    if row is None:
        # Ownership failures are intentionally indistinguishable from a
        # missing incident.
        raise HTTPException(status_code=404, detail="Incident not found")
    if row[1] != "ready":
        raise HTTPException(
            status_code=409,
            detail="Incident clip is not ready for playback",
        )

    _safe_clip_path(incident_id, row[0], settings, require_file=True)
    expires = int(time.time()) + settings.playback_url_seconds
    return PlaybackResponse(
        incident_id=str(incident_id),
        video_version=int(row[2]),
        playback_url=_signed_clip_url(
            request,
            incident_id,
            principal.id,
            expires,
            settings,
            download=False,
        ),
        download_url=_signed_clip_url(
            request,
            incident_id,
            principal.id,
            expires,
            settings,
            download=True,
        ),
        expires_at=datetime.fromtimestamp(expires, tz=timezone.utc),
    )


@router.get("/playback/incidents/{incident_id}")
def serve_incident_clip(
    incident_id: UUID,
    uid: str = Query(...),
    exp: int = Query(...),
    sig: str = Query(...),
    download: bool = Query(default=False),
    connection: psycopg.Connection = Depends(db.get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Serve a ready local clip after verifying its short-lived signature."""

    action = "download" if download else "playback"
    _verify_signature(f"incident|{incident_id}|{uid}|{action}", exp, sig, settings)

    row = connection.execute(
        """
        SELECT storage_path, user_id, processing_state
        FROM incident
        WHERE id = %s
        """,
        (incident_id,),
    ).fetchone()

    if row is None or row[1] is None or str(row[1]) != uid:
        raise HTTPException(status_code=404, detail="Incident not found")
    if row[2] != "ready":
        raise HTTPException(status_code=409, detail="Incident clip is not ready")

    path = _safe_clip_path(incident_id, row[0], settings, require_file=True)
    assert path is not None
    headers = {"Cache-Control": "private, max-age=300"}
    if download:
        headers["Content-Disposition"] = (
            f'attachment; filename="incident-{incident_id}.mp4"'
        )
    return FileResponse(path, media_type="video/mp4", headers=headers)


@router.get("/playback/incidents/{incident_id}/thumbnail")
def serve_incident_thumbnail(
    incident_id: UUID,
    uid: str = Query(...),
    exp: int = Query(...),
    sig: str = Query(...),
    connection: psycopg.Connection = Depends(db.get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Serve a still from a ready clip after verifying its short-lived signature."""

    _verify_signature(f"incident|{incident_id}|{uid}|thumbnail", exp, sig, settings)

    row = connection.execute(
        """
        SELECT storage_path, user_id, processing_state,
               trigger_at, actual_start, duration_seconds
        FROM incident
        WHERE id = %s
        """,
        (incident_id,),
    ).fetchone()

    if row is None or row[1] is None or str(row[1]) != uid:
        raise HTTPException(status_code=404, detail="Incident not found")
    if row[2] != "ready":
        raise HTTPException(status_code=409, detail="Incident clip is not ready")

    clip = _safe_clip_path(incident_id, row[0], settings, require_file=True)
    assert clip is not None
    thumbnail = clip.with_name(THUMBNAIL_NAME)
    if not thumbnail.is_file():
        _make_thumbnail(clip, thumbnail, _thumbnail_offset(row[3], row[4], row[5]), settings)
    return FileResponse(
        thumbnail,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.delete("/incidents/{incident_id}", status_code=204)
def delete_incident(
    incident_id: UUID,
    principal: Principal = Depends(get_current_principal),
    connection: psycopg.Connection = Depends(db.get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Delete an owned incident and its local clip."""

    row = connection.execute(
        """
        SELECT storage_path, processing_state
        FROM incident
        WHERE id = %s AND user_id = %s
        FOR UPDATE
        """,
        (incident_id, principal.id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    if row[1] == "assembling":
        raise HTTPException(status_code=409, detail="Incident clip is being assembled")

    clip_path = _safe_clip_path(incident_id, row[0], settings, require_file=False)
    if clip_path is not None and clip_path.exists():
        try:
            clip_path.unlink()
            clip_path.with_name(THUMBNAIL_NAME).unlink(missing_ok=True)
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail="Incident clip could not be deleted",
            ) from exc

    # Shared segments must stay preserved for other incidents. Release
    # only links owned by this incident, then select a remaining owner.
    removed = connection.execute(
        """
        DELETE FROM incident_segment
        WHERE incident_id = %s
        RETURNING segment_id
        """,
        (incident_id,),
    ).fetchall()
    if removed:
        connection.execute(
            """
            UPDATE segment AS s
            SET incident_id = (
                    SELECT link.incident_id
                    FROM incident_segment AS link
                    WHERE link.segment_id = s.id
                    ORDER BY link.incident_id LIMIT 1
                ),
                status = CASE WHEN EXISTS (
                    SELECT 1 FROM incident_segment AS link
                    WHERE link.segment_id = s.id
                ) THEN 'preserved' ELSE 'temporary' END
            WHERE s.id = ANY(%s)
            """,
            ([item[0] for item in removed],),
        )
    connection.execute(
        """
        DELETE FROM incident
        WHERE id = %s AND user_id = %s
        """,
        (incident_id, principal.id),
    )

    if clip_path is not None:
        try:
            clip_path.parent.rmdir()
        except OSError:
            # The directory may contain another local artifact; only the clip
            # itself is owned by this endpoint.
            pass
    return Response(status_code=204)
