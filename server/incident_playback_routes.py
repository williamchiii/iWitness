"""Private playback and deletion endpoints for saved incidents."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
from pathlib import Path
import time
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

try:
    from . import db
    from .auth import Principal, get_current_principal
    from .config import SERVER_ROOT, settings
except ImportError:
    # Supports ``uvicorn main:app`` when launched from the server directory.
    import db
    from auth import Principal, get_current_principal
    from config import SERVER_ROOT, settings


router = APIRouter()


class PlaybackResponse(BaseModel):
    """Short-lived URLs for an owned, ready incident clip."""

    incident_id: str
    video_version: int
    playback_url: str
    download_url: str
    expires_at: datetime


def _signature(payload: str, expires: int) -> str:
    """Sign a playback URL payload with the configured server secret."""

    message = f"{payload}|{expires}".encode("utf-8")
    return hmac.new(
        settings.playback_signing_secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def _verify_signature(payload: str, expires: int, signature: str) -> None:
    """Reject expired or forged local playback URLs."""

    if expires <= int(time.time()):
        raise HTTPException(status_code=403, detail="Playback URL expired")
    expected = _signature(payload, expires)
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=403, detail="Invalid playback signature")


def _incident_directory(incident_id: UUID) -> Path:
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
    *,
    require_file: bool,
) -> Path | None:
    """Resolve a stored clip only inside its incident-specific directory."""

    if not storage_path:
        if require_file:
            raise HTTPException(status_code=404, detail="Incident clip not found")
        return None

    directory = _incident_directory(incident_id)
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
    *,
    download: bool,
) -> str:
    """Build a signed URL that can be used without an Authorization header."""

    action = "download" if download else "playback"
    signature = _signature(
        f"incident|{incident_id}|{user_id}|{action}",
        expires,
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


@router.get(
    "/incidents/{incident_id}/playback",
    response_model=PlaybackResponse,
)
def get_incident_playback(
    incident_id: UUID,
    request: Request,
    principal: Principal = Depends(get_current_principal),
) -> PlaybackResponse:
    """Issue signed playback and download URLs for an owned ready clip."""

    with db.connect() as connection:
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

    _safe_clip_path(incident_id, row[0], require_file=True)
    expires = int(time.time()) + settings.playback_url_seconds
    return PlaybackResponse(
        incident_id=str(incident_id),
        video_version=int(row[2]),
        playback_url=_signed_clip_url(
            request,
            incident_id,
            principal.id,
            expires,
            download=False,
        ),
        download_url=_signed_clip_url(
            request,
            incident_id,
            principal.id,
            expires,
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
) -> FileResponse:
    """Serve a ready local clip after verifying its short-lived signature."""

    action = "download" if download else "playback"
    _verify_signature(f"incident|{incident_id}|{uid}|{action}", exp, sig)

    with db.connect() as connection:
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

    path = _safe_clip_path(incident_id, row[0], require_file=True)
    assert path is not None
    headers = {"Cache-Control": "private, max-age=300"}
    if download:
        headers["Content-Disposition"] = (
            f'attachment; filename="incident-{incident_id}.mp4"'
        )
    return FileResponse(path, media_type="video/mp4", headers=headers)


@router.delete("/incidents/{incident_id}", status_code=204)
def delete_incident(
    incident_id: UUID,
    principal: Principal = Depends(get_current_principal),
) -> Response:
    """Delete an owned incident and its local clip."""

    with db.connect() as connection:
        row = connection.execute(
            """
            SELECT storage_path
            FROM incident
            WHERE id = %s AND user_id = %s
            FOR UPDATE
            """,
            (incident_id, principal.id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Incident not found")

        clip_path = _safe_clip_path(incident_id, row[0], require_file=False)
        if clip_path is not None and clip_path.exists():
            try:
                clip_path.unlink()
            except OSError as exc:
                raise HTTPException(
                    status_code=500,
                    detail="Incident clip could not be deleted",
                ) from exc

        # Preserved source segments are part of the rolling camera buffer.
        # Release them before deleting the incident so the segment check
        # constraint remains valid and retention can manage them normally.
        connection.execute(
            """
            UPDATE segment
            SET status = 'temporary', incident_id = NULL
            WHERE incident_id = %s
            """,
            (incident_id,),
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
