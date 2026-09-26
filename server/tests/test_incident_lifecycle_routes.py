"""Focused tests for authenticated incident lifecycle routes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
from typing import Any
from unittest import TestCase
from unittest.mock import patch
from uuid import UUID

os.environ.setdefault("PLAYBACK_SIGNING_SECRET", "incident-lifecycle-test-secret")

try:
    from server.auth import Principal
    from server import incident_lifecycle_routes as lifecycle_routes
except ModuleNotFoundError:
    from auth import Principal
    import incident_lifecycle_routes as lifecycle_routes

claim_incident = lifecycle_routes.claim_incident
get_incident = lifecycle_routes.get_incident
list_incidents = lifecycle_routes.list_incidents

from fastapi import HTTPException


INCIDENT_ID = UUID("11111111-1111-1111-1111-111111111111")
TRIP_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("33333333-3333-3333-3333-333333333333")
OTHER_USER_ID = UUID("44444444-4444-4444-4444-444444444444")
TRIP_TOKEN = "trip-token"


class _Result:
    def __init__(self, rows: Any = None, *, many: bool = False) -> None:
        self.rows = rows
        self.many = many

    def fetchone(self) -> Any:
        if self.many:
            raise AssertionError("fetchone called for a multi-row response")
        return self.rows

    def fetchall(self) -> list[Any]:
        if not self.many:
            raise AssertionError("fetchall called for a single-row response")
        return self.rows


class _Connection:
    def __init__(self, responses: list[_Result]) -> None:
        self.responses = responses
        self.queries: list[tuple[str, tuple[Any, ...] | None]] = []

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> _Result:
        self.queries.append((query, params))
        if not self.responses:
            raise AssertionError(f"Unexpected query: {query}")
        return self.responses.pop(0)


def _principal(user_id: UUID = USER_ID) -> Principal:
    return Principal(
        id=str(user_id),
        email="student@example.com",
        display_name="Student",
        avatar_url=None,
        role="authenticated",
    )


def _incident_row(
    *,
    user_id: UUID | None = USER_ID,
    claim_state: str = "claimed",
    expires_at: datetime | None = None,
) -> tuple[Any, ...]:
    now = datetime.now(timezone.utc)
    return (
        INCIDENT_ID,
        TRIP_ID,
        "camera-demo",
        "Demo camera",
        "replay",
        now,
        now - timedelta(seconds=60),
        now + timedelta(seconds=15),
        now - timedelta(seconds=10),
        now,
        None,
        None,
        10.0,
        100,
        "abc123",
        "ready",
        claim_state,
        expires_at,
        1,
        None,
    )


def _trip_row(claim_state: str = "unclaimed", expires_at: datetime | None = None):
    return (
        TRIP_ID,
        claim_state,
        expires_at,
        hashlib.sha256(TRIP_TOKEN.encode("utf-8")).hexdigest(),
    )


class IncidentLifecycleRouteTests(TestCase):
    """Exercise authorization and first-claim-wins behavior without Postgres."""

    def test_claim_creates_user_and_claims_incident(self) -> None:
        connection = _Connection(
            [
                _Result(_trip_row()),
                _Result(),  # app_user upsert
                _Result((INCIDENT_ID,)),
                _Result(_incident_row()),
            ]
        )

        with patch.object(lifecycle_routes.db, "connect", return_value=connection):
            response = claim_incident(
                INCIDENT_ID,
                principal=_principal(),
                x_trip_token=TRIP_TOKEN,
            )

        self.assertEqual(response.id, str(INCIDENT_ID))
        self.assertEqual(response.claim_state, "claimed")
        self.assertIsNone(response.expires_at)
        self.assertEqual(connection.queries[2][1], (USER_ID, INCIDENT_ID))

    def test_claim_rejects_wrong_trip_token(self) -> None:
        connection = _Connection([_Result(_trip_row())])

        with patch.object(lifecycle_routes.db, "connect", return_value=connection):
            with self.assertRaises(HTTPException) as raised:
                claim_incident(
                    INCIDENT_ID,
                    principal=_principal(),
                    x_trip_token="wrong-token",
                )

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(len(connection.queries), 1)

    def test_expired_unclaimed_incident_returns_410(self) -> None:
        connection = _Connection(
            [
                _Result(
                    _trip_row(
                        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
                    )
                ),
            ]
        )

        with patch.object(lifecycle_routes.db, "connect", return_value=connection):
            with self.assertRaises(HTTPException) as raised:
                claim_incident(
                    INCIDENT_ID,
                    principal=_principal(),
                    x_trip_token=TRIP_TOKEN,
                )

        self.assertEqual(raised.exception.status_code, 410)
        self.assertEqual(len(connection.queries), 1)

    def test_second_claim_returns_409(self) -> None:
        connection = _Connection([_Result(_trip_row(claim_state="claimed"))])

        with patch.object(lifecycle_routes.db, "connect", return_value=connection):
            with self.assertRaises(HTTPException) as raised:
                claim_incident(
                    INCIDENT_ID,
                    principal=_principal(),
                    x_trip_token=TRIP_TOKEN,
                )

        self.assertEqual(raised.exception.status_code, 409)

    def test_list_uses_verified_user_id_and_newest_first_query(self) -> None:
        rows = [_incident_row(), _incident_row()]
        connection = _Connection([_Result(rows, many=True)])

        with patch.object(lifecycle_routes.db, "connect", return_value=connection):
            response = list_incidents(principal=_principal())

        self.assertEqual(len(response), 2)
        self.assertEqual(connection.queries[0][1], (USER_ID,))
        self.assertIn("ORDER BY i.trigger_at DESC", connection.queries[0][0])

    def test_detail_returns_404_when_incident_is_not_owned(self) -> None:
        connection = _Connection([_Result(None)])

        with patch.object(lifecycle_routes.db, "connect", return_value=connection):
            with self.assertRaises(HTTPException) as raised:
                get_incident(INCIDENT_ID, principal=_principal(OTHER_USER_ID))

        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    import unittest

    unittest.main()
