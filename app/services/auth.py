"""Neon Auth (Managed Better Auth) integration.

The official Neon Auth SDK is TypeScript-only. LoWi is a Python service, so this
module talks to the Managed Better Auth REST API directly and verifies Neon
JWTs with the branch JWKS. Keep this behind `AuthProvider` so a small proxy
service can replace it without touching the API routes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx
import jwt
from jwt import PyJWKClient

from app.config import Settings

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """An expected authentication failure with a safe client-facing message."""

    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class AuthIdentity:
    id: str
    email: str
    name: str
    email_verified: bool = True


class AuthProvider(Protocol):
    def register(self, email: str, password: str, name: str) -> AuthIdentity: ...

    def login(self, email: str, password: str) -> AuthIdentity: ...

    def verify_jwt(self, token: str) -> AuthIdentity: ...


class NeonAuthProvider:
    """Thin client for the branch's Managed Better Auth REST API."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self._client = client or httpx.Client(timeout=20)
        self._jwks: PyJWKClient | None = None

    def _url(self, path: str) -> str:
        base = self.settings.neon_auth_base_url.rstrip("/")
        if base.endswith("/auth"):
            return f"{base}{path}"
        return f"{base}/auth{path}"

    def _request(self, path: str, payload: dict) -> dict:
        try:
            response = self._client.post(self._url(path), json=payload)
        except httpx.HTTPError as exc:
            logger.warning("Neon Auth request failed: %s", exc)
            raise AuthError("Authentication service is unavailable", 502) from exc

        if response.status_code >= 400:
            message = _error_message(response)
            logger.info("Neon Auth rejected %s: %s", path, message)
            raise AuthError(message, 401 if response.status_code in {400, 401, 403} else 502)

        try:
            body = response.json()
        except ValueError as exc:
            raise AuthError("Authentication service returned an invalid response", 502) from exc
        if not isinstance(body, dict):
            raise AuthError("Authentication service returned an invalid response", 502)
        return body

    def register(self, email: str, password: str, name: str) -> AuthIdentity:
        body = self._request(
            "/sign-up/email",
            {"email": email, "password": password, "name": name},
        )
        return _identity_from_body(body)

    def login(self, email: str, password: str) -> AuthIdentity:
        body = self._request("/sign-in/email", {"email": email, "password": password})
        return _identity_from_body(body)

    def verify_jwt(self, token: str) -> AuthIdentity:
        if self._jwks is None:
            if not self.settings.neon_auth_jwks_url:
                raise AuthError("JWT verification is not configured", 500)
            self._jwks = PyJWKClient(self.settings.neon_auth_jwks_url)

        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)
        except Exception as exc:
            raise AuthError("Invalid token", 401) from exc

        options = {"require": ["exp", "sub"]}
        kwargs: dict = {"algorithms": ["EdDSA", "RS256", "ES256"]}
        if self.settings.neon_auth_issuer:
            kwargs["issuer"] = self.settings.neon_auth_issuer
        if self.settings.neon_auth_audience:
            kwargs["audience"] = self.settings.neon_auth_audience

        try:
            claims = jwt.decode(token, signing_key.key, options=options, **kwargs)
        except jwt.InvalidTokenError as exc:
            raise AuthError("Invalid token", 401) from exc

        email = str(claims.get("email") or "")
        if not claims.get("sub") or not email:
            raise AuthError("Token is missing required claims", 401)
        return AuthIdentity(
            id=str(claims["sub"]),
            email=email,
            name=str(claims.get("name") or email.split("@")[0]),
            email_verified=bool(claims.get("emailVerified", True)),
        )


def _identity_from_body(body: dict) -> AuthIdentity:
    user = body.get("user") if isinstance(body.get("user"), dict) else body
    if not isinstance(user, dict):
        raise AuthError("Authentication service returned an invalid user", 502)
    email = str(user.get("email") or "")
    user_id = str(user.get("id") or "")
    if not email or not user_id:
        raise AuthError("Authentication service returned an incomplete user", 502)
    return AuthIdentity(
        id=user_id,
        email=email,
        name=str(user.get("name") or email.split("@")[0]),
        email_verified=bool(user.get("emailVerified", True)),
    )


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return "Authentication failed"
    if isinstance(body, dict):
        for key in ("message", "error"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value[:300]
    return "Authentication failed"


def build_auth_provider(settings: Settings) -> AuthProvider | None:
    if settings.auth_mode != "neon":
        return None
    return NeonAuthProvider(settings)
