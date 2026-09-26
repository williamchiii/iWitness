"""Exercise the authenticated /me endpoint through the ASGI app."""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch


os.environ.setdefault("PLAYBACK_SIGNING_SECRET", "profile-route-test-secret")

from server.main import app


SECRET = "profile-test-secret"
ISSUER = "https://example.supabase.co/auth/v1"


def _part(value: object) -> str:
    """Encode one JWT part for the test issuer."""

    data = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _token(**overrides: object) -> str:
    """Sign a short-lived Supabase-style token for route tests."""

    claims: dict[str, object] = {
        "sub": "22222222-2222-2222-2222-222222222222",
        "email": "owner@example.com",
        "user_metadata": {
            "full_name": "Owner",
            "avatar_url": "https://example.com/avatar.png",
        },
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
        "iss": ISSUER,
        "aud": "authenticated",
        "role": "authenticated",
    }
    claims.update(overrides)
    header = _part({"alg": "HS256", "typ": "JWT"})
    payload = _part(claims)
    message = f"{header}.{payload}".encode("ascii")
    signature = hmac.new(SECRET.encode(), message, hashlib.sha256).digest()
    return f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"


def _get_me(authorization: str | None = None, query: bytes = b"") -> tuple[int, dict]:
    """Make a real ASGI request without starting the recorder lifespan."""

    async def run() -> tuple[int, dict]:
        messages: list[dict] = []
        received = False

        async def receive() -> dict:
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": b"", "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message: dict) -> None:
            messages.append(message)

        headers = [] if authorization is None else [(b"authorization", authorization.encode())]
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/me",
            "raw_path": b"/me",
            "query_string": query,
            "root_path": "",
            "headers": headers,
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
        await app(scope, receive, send)
        body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        return messages[0]["status"], json.loads(body)

    return asyncio.run(run())


class ProfileRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {
                "SUPABASE_JWT_SECRET": SECRET,
                "SUPABASE_JWT_ISSUER": ISSUER,
                "SUPABASE_JWT_AUDIENCE": "authenticated",
            },
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()

    def test_returns_exact_user_shape_from_verified_token(self) -> None:
        status, body = _get_me(
            f"Bearer {_token()}", query=b"user_id=someone-else&email=other@example.com"
        )

        self.assertEqual(status, 200)
        self.assertEqual(
            body,
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "email": "owner@example.com",
                "display_name": "Owner",
                "avatar_url": "https://example.com/avatar.png",
            },
        )

    def test_optional_profile_fields_are_null(self) -> None:
        status, body = _get_me(f"Bearer {_token(user_metadata={})}")

        self.assertEqual(status, 200)
        self.assertIsNone(body["display_name"])
        self.assertIsNone(body["avatar_url"])

    def test_missing_token_is_rejected(self) -> None:
        status, body = _get_me()

        self.assertEqual(status, 401)
        self.assertEqual(body["detail"], "Invalid or missing access token")

    def test_invalid_token_is_rejected(self) -> None:
        status, body = _get_me("Bearer invalid-token")

        self.assertEqual(status, 401)
        self.assertEqual(body["detail"], "Invalid or missing access token")

    def test_missing_email_is_rejected_to_preserve_user_shape(self) -> None:
        status, body = _get_me(f"Bearer {_token(email=None)}")

        self.assertEqual(status, 401)
        self.assertEqual(body["detail"], "Authenticated user email is missing")


if __name__ == "__main__":
    unittest.main()
