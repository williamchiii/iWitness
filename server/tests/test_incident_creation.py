"""Focused checks for incident ownership and shared pre-trigger footage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import unittest
from unittest.mock import patch
from uuid import UUID

os.environ.setdefault("PLAYBACK_SIGNING_SECRET", "incident-creation-test-secret")

from server import api
from server.auth import Principal
from server.schemas import TripResponse


INCIDENT_ID = UUID("11111111-1111-1111-1111-111111111111")
TRIP_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("33333333-3333-3333-3333-333333333333")
TRIGGER_AT = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)
REQUESTED_START = TRIGGER_AT - timedelta(seconds=60)


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
            return _Result((INCIDENT_ID, REQUESTED_START, TRIGGER_AT))
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
        ):
            response = api.create_incident(
                TRIP_ID, x_trip_token="trip-token", principal=principal,
                connection=connection, settings=api.get_settings(),
            )

        self.assertEqual(response.claim_state, "claimed")
        self.assertTrue(connection.queries[0][0].lstrip().startswith("INSERT INTO app_user"))
        self.assertIn(USER_ID, connection.queries[1][1])
        self.assertTrue(any(
            "INSERT INTO incident_segment" in query for query, _ in connection.queries
        ))
        preserve_queries = [
            (query, params) for query, params in connection.queries
            if "UPDATE segment AS s" in query or "INSERT INTO incident_segment" in query
        ]
        self.assertEqual(len(preserve_queries), 2)
        for query, params in preserve_queries:
            self.assertIn("s.actual_start < %s", query)
            self.assertIn("s.actual_end > %s", query)
            self.assertEqual(
                params, (INCIDENT_ID, "camera-demo", TRIGGER_AT, REQUESTED_START)
            )


if __name__ == "__main__":
    unittest.main()
