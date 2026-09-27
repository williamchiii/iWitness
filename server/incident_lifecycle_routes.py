"""Authenticated incident claim, listing, and detail endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
from uuid import UUID

import psycopg

from fastapi import APIRouter, Depends, Header, HTTPException

from . import db
from .auth import Principal, get_current_principal
from .incident_playback_routes import signed_thumbnail_url
from .incident_schemas import IncidentResponse, saved_clip_deletes_at


router = APIRouter()


_INCIDENT_COLUMNS = """
    i.id, i.trip_id, i.camera_id, c.name, c.source_type,
    i.trigger_at, i.requested_start, i.requested_end,
    i.actual_start, i.actual_end, i.source_start, i.source_end,
    i.duration_seconds, i.size_bytes, i.sha256,
    i.processing_state, i.claim_state, i.expires_at,
    i.video_version, i.error
"""


def _incident_from_row(row: tuple[object, ...]) -> IncidentResponse:
    """Convert the shared incident query shape into the public response."""

    return IncidentResponse(
        id=str(row[0]),
        trip_id=str(row[1]),
        camera_id=str(row[2]),
        camera_name=str(row[3]),
        source_type=str(row[4]),
        trigger_at=_as_utc(row[5]),
        requested_start=_as_utc(row[6]),
        requested_end=_as_utc(row[7]),
        actual_start=_as_utc(row[8]) if row[8] is not None else None,
        actual_end=_as_utc(row[9]) if row[9] is not None else None,
        source_start=_as_utc(row[10]) if row[10] is not None else None,
        source_end=_as_utc(row[11]) if row[11] is not None else None,
        duration_seconds=row[12],
        size_bytes=row[13],
        sha256=row[14],
        processing_state=str(row[15]),
        claim_state=str(row[16]),
        expires_at=_as_utc(row[17]) if row[17] is not None else None,
        video_version=row[18],
        error=row[19],
        deletes_at=saved_clip_deletes_at(str(row[16]), _as_utc(row[5])),
    )


def _for_owner(incident: IncidentResponse, user_id: UUID) -> IncidentResponse:
    """Add the owner-only thumbnail link once the clip is ready."""

    if incident.processing_state != "ready":
        return incident
    return incident.model_copy(
        update={"thumbnail_url": signed_thumbnail_url(incident.id, str(user_id))}
    )


def _token_hash(token: str) -> str:
    """Hash an anonymous trip token for comparison with the database."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _user_id(principal: Principal) -> UUID:
    """Convert the verified Supabase subject into the database user id."""

    try:
        return UUID(principal.id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(
            status_code=401,
            detail="Authenticated user id is invalid",
        ) from exc


def _incident_for_trip(
    connection: object,
    incident_id: UUID,
    trip_token: str,
) -> tuple[object, ...]:
    """Load and lock an incident after checking its trip token."""

    row = connection.execute(
        """
        SELECT i.trip_id, i.claim_state, i.expires_at,
               t.anonymous_token_hash
        FROM incident AS i
        JOIN trip AS t ON t.id = i.trip_id
        WHERE i.id = %s
        FOR UPDATE OF i
        """,
        (incident_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    if not hmac.compare_digest(str(row[3]), _token_hash(trip_token)):
        raise HTTPException(status_code=403, detail="Invalid trip token")
    return row


def _incident_row(connection: object, incident_id: UUID, user_id: UUID):
    """Load one incident only when it belongs to the verified user."""

    return connection.execute(
        f"""
        SELECT {_INCIDENT_COLUMNS}
        FROM incident AS i
        JOIN camera AS c ON c.id = i.camera_id
        WHERE i.id = %s AND i.user_id = %s
        """,
        (incident_id, user_id),
    ).fetchone()


@router.post(
    "/incidents/{incident_id}/claim",
    response_model=IncidentResponse,
)
def claim_incident(
    incident_id: UUID,
    principal: Principal = Depends(get_current_principal),
    x_trip_token: str | None = Header(default=None, alias="X-Trip-Token"),
    connection: psycopg.Connection = Depends(db.get_db),
) -> IncidentResponse:
    """Attach an unclaimed incident to the first verified user who claims it."""

    if not x_trip_token:
        raise HTTPException(status_code=403, detail="Trip token required")

    user_id = _user_id(principal)
    if not principal.email:
        raise HTTPException(
            status_code=401,
            detail="Authenticated user email is missing",
        )

    expired = False
    response_row: tuple[object, ...] | None = None
    incident = _incident_for_trip(connection, incident_id, x_trip_token)
    claim_state = str(incident[1])
    expires_at = incident[2]

    if claim_state == "claimed":
        raise HTTPException(status_code=409, detail="Incident already claimed")
    if claim_state == "expired":
        expired = True
    elif expires_at is not None and _as_utc(expires_at) <= datetime.now(
        timezone.utc
    ):
        # Leave the row unclaimed so the incident worker can release its
        # shared segment links and remove its clip during expiry cleanup.
        expired = True
    else:
        connection.execute(
            """
            INSERT INTO app_user (id, email, display_name, avatar_url)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                email = EXCLUDED.email,
                display_name = COALESCE(EXCLUDED.display_name, app_user.display_name),
                avatar_url = COALESCE(EXCLUDED.avatar_url, app_user.avatar_url)
            """,
            (
                user_id,
                principal.email,
                principal.display_name,
                principal.avatar_url,
            ),
        )
        response_row = connection.execute(
            """
            UPDATE incident
            SET user_id = %s, claim_state = 'claimed', expires_at = NULL
            WHERE id = %s
              AND claim_state = 'unclaimed'
              AND (expires_at IS NULL OR expires_at > clock_timestamp())
            RETURNING id
            """,
            (user_id, incident_id),
        ).fetchone()

        if response_row is not None:
            response_row = _incident_row(connection, incident_id, user_id)
        else:
            # This is defensive for databases that do not serialize the
            # lock as expected. Classify a concurrent claim consistently.
            current = connection.execute(
                """
                SELECT claim_state, expires_at <= clock_timestamp()
                FROM incident
                WHERE id = %s
                """,
                (incident_id,),
            ).fetchone()
            if current is not None and (
                str(current[0]) == "expired" or current[1] is True
            ):
                expired = True

    if expired:
        raise HTTPException(
            status_code=410,
            detail="Unclaimed incident expired",
        )
    if response_row is None:
        raise HTTPException(status_code=409, detail="Incident already claimed")
    return _incident_from_row(response_row)


@router.get("/incidents", response_model=list[IncidentResponse])
def list_incidents(
    principal: Principal = Depends(get_current_principal),
    connection: psycopg.Connection = Depends(db.get_db),
) -> list[IncidentResponse]:
    """Return metadata for incidents owned by the verified user."""

    user_id = _user_id(principal)
    rows = connection.execute(
        f"""
        SELECT {_INCIDENT_COLUMNS}
        FROM incident AS i
        JOIN camera AS c ON c.id = i.camera_id
        WHERE i.user_id = %s
        ORDER BY i.trigger_at DESC
        """,
        (user_id,),
    ).fetchall()
    return [_for_owner(_incident_from_row(row), user_id) for row in rows]


@router.get("/incidents/{incident_id}", response_model=IncidentResponse)
def get_incident(
    incident_id: UUID,
    principal: Principal = Depends(get_current_principal),
    connection: psycopg.Connection = Depends(db.get_db),
) -> IncidentResponse:
    """Return one incident only when it belongs to the verified user."""

    user_id = _user_id(principal)
    row = _incident_row(connection, incident_id, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return _for_owner(_incident_from_row(row), user_id)


def _as_utc(value: datetime) -> datetime:
    """Normalize a database timestamp for expiration comparisons."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
