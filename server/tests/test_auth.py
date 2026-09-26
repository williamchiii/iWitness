"""Focused tests for Supabase access-token verification."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

try:
    from server.auth import (
        AuthConfigurationError,
        InvalidAccessToken,
        Principal,
        get_current_principal,
        get_optional_principal,
        verify_access_token,
    )
except ModuleNotFoundError:
    from auth import (
        AuthConfigurationError,
        InvalidAccessToken,
        Principal,
        get_current_principal,
        get_optional_principal,
        verify_access_token,
    )


def _part(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode("ascii")


def _token(secret: str, **claims: object) -> str:
    header = _part({"alg": "HS256", "typ": "JWT"})
    payload = _part(claims)
    message = f"{header}.{payload}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{header}.{payload}.{encoded_signature}"


class AuthTests(unittest.TestCase):
    """Verify claim validation and FastAPI dependency behavior."""

    secret = "test-secret"
    issuer = "https://example.supabase.co/auth/v1"

    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {
                "SUPABASE_JWT_SECRET": self.secret,
                "SUPABASE_JWT_ISSUER": self.issuer,
                "SUPABASE_JWT_AUDIENCE": "authenticated",
            },
            clear=True,
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()

    def _claims(self, **overrides: object) -> dict[str, object]:
        claims: dict[str, object] = {
            "sub": "user-123",
            "email": "student@example.com",
            "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
            "iss": self.issuer,
            "aud": "authenticated",
            "role": "authenticated",
        }
        claims.update(overrides)
        return claims

    def _token_from_claims(self, **overrides: object) -> str:
        return _token(self.secret, **self._claims(**overrides))

    def test_valid_token_returns_typed_principal(self) -> None:
        principal = verify_access_token(self._token_from_claims())

        self.assertIsInstance(principal, Principal)
        self.assertEqual(principal.id, "user-123")
        self.assertEqual(principal.email, "student@example.com")

    def test_bad_signature_is_rejected(self) -> None:
        token = self._token_from_claims()
        header, payload, signature = token.split(".")
        altered_signature = ("A" if signature[0] != "A" else "B") + signature[1:]
        altered = f"{header}.{payload}.{altered_signature}"

        with self.assertRaises(InvalidAccessToken):
            verify_access_token(altered)

    def test_expired_token_is_rejected(self) -> None:
        token = self._token_from_claims(
            exp=(datetime.now(timezone.utc) - timedelta(seconds=1)).timestamp()
        )

        with self.assertRaises(InvalidAccessToken):
            verify_access_token(token)

    def test_missing_header_maps_to_401(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            get_current_principal(None)

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.headers["WWW-Authenticate"], "Bearer")

    def test_invalid_header_maps_to_401(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            get_current_principal("Basic abc")

        self.assertEqual(raised.exception.status_code, 401)

    def test_invalid_bearer_token_maps_to_401(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            get_current_principal("Bearer malformed-token")

        self.assertEqual(raised.exception.status_code, 401)

    def test_supabase_url_does_not_override_secret_mode(self) -> None:
        token = self._token_from_claims()
        with patch.dict(
            os.environ,
            {"SUPABASE_URL": "https://example.supabase.co"},
        ):
            principal = verify_access_token(token)

        self.assertEqual(principal.id, "user-123")

    def test_optional_dependency_allows_missing_header(self) -> None:
        self.assertIsNone(get_optional_principal(None))

    def test_missing_verifier_configuration_is_explicit(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(AuthConfigurationError):
                verify_access_token("not-a-token")


if __name__ == "__main__":
    unittest.main()
