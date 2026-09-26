"""Focused tests for authenticated incident lifecycle routes."""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from typing import Any
from unittest import TestCase
from unittest.mock import patch
from uuid import UUID
from fastapi import HTTPException

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


def _signed_token(user_id: UUID) -> str:
    """Make a locally verifiable access token for an ASGI request."""

    def part(value: dict[str, object]) -> str:
        data = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = part({"alg": "HS256", "typ": "JWT"})
    payload = part({
        "sub": str(user_id),
        "aud": "authenticated",
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
    })
    message = f"{header}.{payload}"
    signature = hmac.new(b"incident-route-test-secret", message.encode(), hashlib.sha256)
    return f"{message}.{base64.urlsafe_b64encode(signature.digest()).rstrip(b'=').decode()}"


def _asgi_get(app: object, path: str, token: str | None = None) -> tuple[int, Any]:
    """Send an HTTP GET through the ASGI app without an HTTP client package."""

    headers = [] if token is None else [
        (b"authorization", f"Bearer {token}".encode())
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("testclient", 0),
        "server": ("testserver", 80),
    }
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    status = next(message["status"] for message in messages
                  if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages
                    if message["type"] == "http.response.body")
    return status, json.loads(body)


class _OwnedIncidentsConnection:
    """Apply the route's SQL owner predicate to two stored incident rows."""

    def __init__(self) -> None:
        self.rows = {
            USER_ID: _incident_row(),
            OTHER_USER_ID: (UUID("55555555-5555-5555-5555-555555555555"),)
            + _incident_row()[1:],
        }

    def __enter__(self) -> "_OwnedIncidentsConnection":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...]) -> _Result:
        if "WHERE i.user_id = %s" in query:
            owner = params[0]
            return _Result([self.rows[owner]], many=True)
        if "WHERE i.id = %s AND i.user_id = %s" in query:
            incident_id, owner = params
            row = self.rows[owner]
            return _Result(row if row[0] == incident_id else None)
        raise AssertionError(f"Owner filter missing from query: {query}")


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

        response = claim_incident(
            INCIDENT_ID,
            principal=_principal(),
            x_trip_token=TRIP_TOKEN,
            connection=connection,
        )

        self.assertEqual(response.id, str(INCIDENT_ID))
        self.assertEqual(response.claim_state, "claimed")
        self.assertIsNone(response.expires_at)
        self.assertEqual(connection.queries[2][1], (USER_ID, INCIDENT_ID))
        self.assertIn("expires_at > clock_timestamp()", connection.queries[2][0])

    def test_claim_requires_trip_token(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            claim_incident(INCIDENT_ID, principal=_principal(), x_trip_token=None)

        self.assertEqual(raised.exception.status_code, 403)

    def test_missing_incident_returns_404(self) -> None:
        connection = _Connection([_Result(None)])

        with self.assertRaises(HTTPException) as raised:
            claim_incident(
                INCIDENT_ID,
                principal=_principal(),
                x_trip_token=TRIP_TOKEN,
                connection=connection,
            )

        self.assertEqual(raised.exception.status_code, 404)

    def test_claim_rejects_wrong_trip_token(self) -> None:
        connection = _Connection([_Result(_trip_row())])

        with self.assertRaises(HTTPException) as raised:
            claim_incident(
                INCIDENT_ID,
                principal=_principal(),
                x_trip_token="wrong-token",
                connection=connection,
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

        with self.assertRaises(HTTPException) as raised:
            claim_incident(
                INCIDENT_ID,
                principal=_principal(),
                x_trip_token=TRIP_TOKEN,
                connection=connection,
            )

        self.assertEqual(raised.exception.status_code, 410)
        self.assertEqual(len(connection.queries), 1)

    def test_second_claim_returns_409(self) -> None:
        connection = _Connection([_Result(_trip_row(claim_state="claimed"))])

        with self.assertRaises(HTTPException) as raised:
            claim_incident(
                INCIDENT_ID,
                principal=_principal(),
                x_trip_token=TRIP_TOKEN,
                connection=connection,
            )

        self.assertEqual(raised.exception.status_code, 409)

    def test_explicitly_expired_incident_returns_410(self) -> None:
        connection = _Connection([_Result(_trip_row(claim_state="expired"))])

        with self.assertRaises(HTTPException) as raised:
            claim_incident(
                INCIDENT_ID,
                principal=_principal(),
                x_trip_token=TRIP_TOKEN,
                connection=connection,
            )

        self.assertEqual(raised.exception.status_code, 410)

    def test_expiry_during_claim_returns_410(self) -> None:
        connection = _Connection(
            [
                _Result(
                    _trip_row(
                        expires_at=datetime.now(timezone.utc) + timedelta(minutes=1)
                    )
                ),
                _Result(),  # app_user upsert
                _Result(None),  # expiry passes before the guarded UPDATE
                _Result(("unclaimed", True)),
            ]
        )

        with self.assertRaises(HTTPException) as raised:
            claim_incident(
                INCIDENT_ID,
                principal=_principal(),
                x_trip_token=TRIP_TOKEN,
                connection=connection,
            )

        self.assertEqual(raised.exception.status_code, 410)
        self.assertIn("expires_at <= clock_timestamp()", connection.queries[3][0])

    def test_list_uses_verified_user_id_and_newest_first_query(self) -> None:
        rows = [_incident_row(), _incident_row()]
        connection = _Connection([_Result(rows, many=True)])

        response = list_incidents(principal=_principal(), connection=connection)

        self.assertEqual(len(response), 2)
        self.assertEqual(connection.queries[0][1], (USER_ID,))
        self.assertIn("ORDER BY i.trigger_at DESC", connection.queries[0][0])

    def test_detail_returns_404_when_incident_is_not_owned(self) -> None:
        connection = _Connection([_Result(None)])

        with self.assertRaises(HTTPException) as raised:
            get_incident(
                INCIDENT_ID, principal=_principal(OTHER_USER_ID), connection=connection
            )

        self.assertEqual(raised.exception.status_code, 404)


class IncidentLifecycleASGITests(TestCase):
    """Exercise the mounted routes with signed users and HTTP responses."""

    def test_list_and_detail_are_private_to_verified_user(self) -> None:
        try:
            from server.main import app
        except ModuleNotFoundError:
            from main import app

        other_incident_id = UUID("55555555-5555-5555-5555-555555555555")
        with (
            patch.dict(os.environ, {"SUPABASE_JWT_SECRET": "incident-route-test-secret"},
                       clear=True),
            patch.object(lifecycle_routes.db, "connect",
                         side_effect=_OwnedIncidentsConnection),
        ):
            for user_id, own_id, hidden_id in (
                (USER_ID, INCIDENT_ID, other_incident_id),
                (OTHER_USER_ID, other_incident_id, INCIDENT_ID),
            ):
                token = _signed_token(user_id)
                list_status, listed = _asgi_get(app, "/incidents", token)
                self.assertEqual(list_status, 200)
                self.assertEqual([item["id"] for item in listed], [str(own_id)])
                self.assertNotIn("user_id", listed[0])

                detail_status, detail = _asgi_get(
                    app, f"/incidents/{own_id}", token
                )
                self.assertEqual(detail_status, 200)
                self.assertEqual(detail["id"], str(own_id))

                hidden_status, hidden = _asgi_get(
                    app, f"/incidents/{hidden_id}", token
                )
                missing_status, missing = _asgi_get(
                    app, f"/incidents/{UUID(int=0)}", token
                )
                self.assertEqual((hidden_status, hidden), (404, missing))
                self.assertEqual(missing_status, 404)

            for path in ("/incidents", f"/incidents/{INCIDENT_ID}"):
                self.assertEqual(_asgi_get(app, path)[0], 401)
                self.assertEqual(_asgi_get(app, path, "invalid-token")[0], 401)


if __name__ == "__main__":
    import unittest

    unittest.main()
