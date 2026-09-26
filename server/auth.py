"""Supabase access-token verification for FastAPI dependencies.

The backend supports the two Supabase JWT configurations used by this
project:

* ``SUPABASE_JWT_SECRET`` verifies legacy HS256 tokens locally with the
  Python standard library.
* ``SUPABASE_JWKS_URL`` (or ``SUPABASE_URL`` plus its standard JWKS path)
  verifies asymmetric tokens through PyJWT's JWKS support. Install
  ``PyJWT[crypto]`` when using this mode.

The module deliberately does not create or accept a user id from a request.
The principal id always comes from the verified token's ``sub`` claim.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
import time
from functools import lru_cache
from typing import Any, Mapping

from fastapi import Header, HTTPException, status


class AuthConfigurationError(RuntimeError):
    """The server is missing the settings required to verify Supabase tokens."""


class InvalidAccessToken(ValueError):
    """The supplied access token is malformed or failed verification."""


@dataclass(frozen=True, slots=True)
class Principal:
    """The trusted identity derived from a verified Supabase access token."""

    id: str
    email: str | None
    display_name: str | None
    avatar_url: str | None
    role: str | None


@dataclass(frozen=True, slots=True)
class _VerificationSettings:
    secret: str | None
    jwks_url: str | None
    issuer: str | None
    audience: str | None
    algorithms: tuple[str, ...]


def _setting(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _verification_settings() -> _VerificationSettings:
    secret = _setting("SUPABASE_JWT_SECRET")
    supabase_url = _setting("SUPABASE_URL")
    configured_jwks_url = _setting("SUPABASE_JWKS_URL")
    jwks_url = configured_jwks_url
    issuer = _setting("SUPABASE_JWT_ISSUER")

    if secret is None and jwks_url is None and supabase_url is not None:
        jwks_url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    if issuer is None and supabase_url is not None:
        issuer = f"{supabase_url.rstrip('/')}/auth/v1"

    if secret is not None and jwks_url is not None:
        raise AuthConfigurationError(
            "Configure exactly one of SUPABASE_JWT_SECRET or SUPABASE_JWKS_URL"
        )
    if secret is None and jwks_url is None:
        raise AuthConfigurationError(
            "Set SUPABASE_JWT_SECRET for HS256 or SUPABASE_JWKS_URL "
            "(and SUPABASE_URL if needed) for JWKS verification"
        )

    configured_algorithms = _setting("SUPABASE_JWT_ALGORITHMS")
    if configured_algorithms is None:
        algorithms = (
            ("HS256",)
            if secret is not None
            else ("RS256", "ES256", "EdDSA")
        )
    else:
        algorithms = tuple(
            algorithm.strip()
            for algorithm in configured_algorithms.split(",")
            if algorithm.strip()
        )
    if not algorithms:
        raise AuthConfigurationError("SUPABASE_JWT_ALGORITHMS cannot be empty")
    if secret is not None and algorithms != ("HS256",):
        raise AuthConfigurationError(
            "SUPABASE_JWT_SECRET may only be used with the HS256 algorithm"
        )

    return _VerificationSettings(
        secret=secret,
        jwks_url=jwks_url,
        issuer=issuer,
        audience=_setting("SUPABASE_JWT_AUDIENCE") or "authenticated",
        algorithms=algorithms,
    )


def _decode_part(value: str) -> bytes:
    if not value:
        raise InvalidAccessToken("JWT part is empty")
    try:
        padded = value + "=" * (-len(value) % 4)
        return base64.b64decode(
            padded.encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError, UnicodeEncodeError) as exc:
        raise InvalidAccessToken("JWT part is not base64url") from exc


def _decode_json(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(_decode_part(value))
    except (InvalidAccessToken, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidAccessToken("JWT part is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise InvalidAccessToken("JWT part must be a JSON object")
    return parsed


def _split_token(
    token: str,
) -> tuple[str, str, str, dict[str, Any], dict[str, Any]]:
    parts = token.split(".")
    if len(parts) != 3:
        raise InvalidAccessToken("JWT must contain three parts")
    header = _decode_json(parts[0])
    claims = _decode_json(parts[1])
    return parts[0], parts[1], parts[2], header, claims


def _require_claims(
    claims: Mapping[str, Any],
    *,
    issuer: str | None,
    audience: str | None,
) -> None:
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise InvalidAccessToken("JWT sub claim is missing")

    expiration = claims.get("exp")
    if isinstance(expiration, bool) or not isinstance(expiration, (int, float)):
        raise InvalidAccessToken("JWT exp claim is missing")
    if expiration <= time.time():
        raise InvalidAccessToken("JWT has expired")

    not_before = claims.get("nbf")
    if not_before is not None:
        if isinstance(not_before, bool) or not isinstance(not_before, (int, float)):
            raise InvalidAccessToken("JWT nbf claim is invalid")
        if not_before > time.time():
            raise InvalidAccessToken("JWT is not active yet")

    if issuer is not None and claims.get("iss") != issuer:
        raise InvalidAccessToken("JWT issuer is invalid")

    if audience is not None:
        token_audience = claims.get("aud")
        if isinstance(token_audience, str):
            matches = token_audience == audience
        elif isinstance(token_audience, list):
            matches = audience in token_audience
        else:
            matches = False
        if not matches:
            raise InvalidAccessToken("JWT audience is invalid")


def _verify_hs256(token: str, settings: _VerificationSettings) -> dict[str, Any]:
    header_part, payload_part, signature_part, header, claims = _split_token(token)
    if header.get("alg") != "HS256":
        raise InvalidAccessToken("JWT algorithm is invalid")
    if settings.secret is None:
        raise AuthConfigurationError("HS256 verifier is not configured")

    signature = _decode_part(signature_part)
    expected = hmac.new(
        settings.secret.encode("utf-8"),
        f"{header_part}.{payload_part}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(signature, expected):
        raise InvalidAccessToken("JWT signature is invalid")
    _require_claims(claims, issuer=settings.issuer, audience=settings.audience)
    return claims


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> Any:
    try:
        import jwt
    except ImportError as exc:
        raise AuthConfigurationError(
            "JWKS verification requires PyJWT[crypto]; install the server "
            "authentication dependency or configure SUPABASE_JWT_SECRET"
        ) from exc
    return jwt.PyJWKClient(url)


def _verify_jwks(token: str, settings: _VerificationSettings) -> dict[str, Any]:
    if settings.jwks_url is None:
        raise AuthConfigurationError("JWKS verifier is not configured")
    try:
        import jwt

        signing_key = _jwks_client(settings.jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=list(settings.algorithms),
            audience=settings.audience,
            issuer=settings.issuer,
            options={"require": ["exp", "sub"]},
        )
    except AuthConfigurationError:
        raise
    except Exception as exc:
        # Do not expose key-fetch, parsing, or library details to callers.
        raise InvalidAccessToken("JWT verification failed") from exc
    if not isinstance(claims, dict):
        raise InvalidAccessToken("JWT claims are invalid")
    return claims


def _principal_from_claims(claims: Mapping[str, Any]) -> Principal:
    metadata = claims.get("user_metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}

    def _text(*values: object) -> str | None:
        for value in values:
            if isinstance(value, str) and value:
                return value
        return None

    return Principal(
        id=str(claims["sub"]),
        email=claims.get("email") if isinstance(claims.get("email"), str) else None,
        display_name=_text(
            metadata.get("full_name"),
            metadata.get("name"),
            claims.get("name"),
        ),
        avatar_url=_text(
            metadata.get("avatar_url"),
            metadata.get("picture"),
            claims.get("picture"),
        ),
        role=claims.get("role") if isinstance(claims.get("role"), str) else None,
    )


def verify_access_token(token: str) -> Principal:
    """Verify a Supabase access token and return its trusted principal."""

    if not token or any(character.isspace() for character in token):
        raise InvalidAccessToken("Access token is malformed")
    settings = _verification_settings()
    claims = (
        _verify_hs256(token, settings)
        if settings.secret is not None
        else _verify_jwks(token, settings)
    )
    return _principal_from_claims(claims)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing access token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _token_from_header(authorization: str | None) -> str:
    if authorization is None:
        raise _unauthorized()
    parts = authorization.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise _unauthorized()
    return parts[1]


def get_current_principal(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> Principal:
    """FastAPI dependency for endpoints that require Supabase sign-in."""

    try:
        return verify_access_token(_token_from_header(authorization))
    except (InvalidAccessToken, AuthConfigurationError):
        # Configuration errors are intentionally indistinguishable from an
        # invalid token at the HTTP boundary, so verifier details do not leak.
        raise _unauthorized()


def get_optional_principal(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> Principal | None:
    """FastAPI dependency for endpoints where a valid token is optional."""

    if authorization is None:
        return None
    try:
        return verify_access_token(_token_from_header(authorization))
    except (InvalidAccessToken, AuthConfigurationError):
        raise _unauthorized()
