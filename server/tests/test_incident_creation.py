"""Focused checks for incident ownership and shared pre-trigger footage."""

from __future__ import annotations

from datetime import datetime, timezone
import os
import unittest
from unittest.mock import patch
from uuid import UUID

os.environ.setdefault("PLAYBACK_SIGNING_SECRET", "incident-creation-test-secret")

try:
    from server import api
    from server.auth import Principal
    from server.schemas import TripResponse
except ModuleNotFoundError:
    import api
    from auth import Principal
    from schemas import TripResponse


INCIDENT_ID = UUID("11111111-1111-1111-1111-111111111111")
TRIP_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("33333333-3333-3333-3333-333333333333")


class _Result:
    def __init__(self, row: object = None) -> None:
        self.row = row

    def fetchone(self) -> object:
        return self.row


class _Connection:
    def __init__(self) -> None:
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...]) -> _Result:
        self.queries.append((query, params))
        normalized = " ".join(query.split()).lower()
        if normalized.startswith("insert into incident ("):
            return _Result((INCIDENT_ID,))
        if normalized.startswith("select i.id"):
            now = datetime.now(timezone.utc)
            return _Result((
                INCIDENT_ID, TRIP_ID, "camera-demo", "Demo camera", "replay",
                now, now, now, None, None, None, None, None, None, None,
                "recording", "claimed",
                None, 1, None,
            ))
        return _Result()


class IncidentCreationTests(unittest.TestCase):
    def test_signed_in_report_attaches_verified_user_and_shared_segments(self) -> None:
        trip = TripResponse(
            id=str(TRIP_ID), camera_id="camera-demo",
            started_at=datetime.now(timezone.utc), ended_at=None, state="active",
        )
        principal = Principal(
            id=str(USER_ID), email="owner@example.com",
            display_name="Owner", avatar_url=None, role="authenticated",
        )
        connection = _Connection()
        with (
            patch.object(api, "_load_trip", return_value=trip),
            patch.object(api.db, "connect", return_value=connection),
        ):
            response = api.create_incident(
                TRIP_ID, x_trip_token="trip-token", principal=principal,
            )

        self.assertEqual(response.claim_state, "claimed")
        self.assertTrue(connection.queries[0][0].lstrip().startswith("INSERT INTO app_user"))
        self.assertIn(USER_ID, connection.queries[1][1])
        self.assertTrue(any(
            "INSERT INTO incident_segment" in query for query, _ in connection.queries
        ))


if __name__ == "__main__":
    unittest.main()
