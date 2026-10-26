from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import jwt
import pytest
from app.config import Settings
from app.db.models import Session as SessionRecord
from app.db.session import SessionLocal
from app.main import create_app
from app.services.auth import AuthError, AuthIdentity, NeonAuthProvider
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient


class FakeAuthProvider:
    def __init__(self, *, verified: bool = True) -> None:
        self.users: dict[str, dict] = {}
        self.otps: dict[str, str] = {}
        self.next_id = 1
        self.verified = verified

    def register(self, email: str, password: str, name: str) -> AuthIdentity:
        if email in self.users:
            raise AuthError("User already exists", 409)
        user_id = f"neon-{self.next_id}"
        self.next_id += 1
        self.users[email] = {
            "id": user_id,
            "password": password,
            "name": name,
            "verified": self.verified,
        }
        return AuthIdentity(
            id=user_id,
            email=email,
            name=name,
            email_verified=self.verified,
        )

    def login(self, email: str, password: str) -> AuthIdentity:
        user = self.users.get(email)
        if user is None or user["password"] != password:
            raise AuthError("Invalid email or password", 401)
        return AuthIdentity(
            id=user["id"],
            email=email,
            name=user["name"],
            email_verified=user["verified"],
        )

    def verify_jwt(self, token: str) -> AuthIdentity:
        raise AuthError("Invalid token", 401)

    def send_verification_otp(self, email: str) -> None:
        if email not in self.users:
            raise AuthError("User not found", 404)
        self.otps[email] = "123456"

    def verify_email_otp(self, email: str, otp: str) -> None:
        if self.otps.get(email) != otp:
            raise AuthError("Invalid verification code", 401)
        self.users[email]["verified"] = True
        self.otps.pop(email, None)


@pytest.fixture
def neon_settings(tmp_path):
    return Settings(
        app_env="test",
        auth_mode="neon",
        database_url="sqlite://",
        data_dir=tmp_path,
        agentrouter_api_key="test-key",
        elevenlabs_api_key="test-key",
        neon_auth_base_url="https://auth.example/neondb/auth",
        neon_auth_jwks_url="https://auth.example/neondb/auth/.well-known/jwks.json",
        session_ttl_days=30,
    )


@pytest.fixture
def neon_client(neon_settings):
    application = create_app(neon_settings)
    with TestClient(application) as test_client:
        test_client.app.state.runtime.auth = FakeAuthProvider()
        yield test_client


def register(client: TestClient, email: str = "ada@example.com") -> dict:
    response = client.post(
        "/auth/register",
        json={"email": email, "password": "correct-horse", "name": "Ada"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_auth_is_required(neon_client):
    assert neon_client.get("/meetings").status_code == 401
    assert neon_client.get("/auth/me").status_code == 401
    assert neon_client.get("/calendar/events").status_code == 401


def test_auth_config_reports_email_verification(neon_client):
    neon_client.app.state.settings.require_email_verification = True
    config = neon_client.get("/auth/config")
    assert config.status_code == 200
    assert config.json()["required"] is True
    assert config.json()["email_verification"] is True


def test_register_login_and_me(neon_client):
    body = register(neon_client)
    assert body["user"]["email"] == "ada@example.com"
    assert body["token"]

    me = neon_client.get("/auth/me", headers=auth_header(body["token"]))
    assert me.status_code == 200
    assert me.json()["email"] == "ada@example.com"

    login = neon_client.post(
        "/auth/login",
        json={"email": "ada@example.com", "password": "correct-horse"},
    )
    assert login.status_code == 200
    assert login.json()["token"] != body["token"]


def test_duplicate_registration_and_bad_password(neon_client):
    register(neon_client)
    duplicate = neon_client.post(
        "/auth/register",
        json={"email": "ada@example.com", "password": "correct-horse", "name": "Ada"},
    )
    assert duplicate.status_code == 409

    bad = neon_client.post(
        "/auth/login",
        json={"email": "ada@example.com", "password": "wrong-password"},
    )
    assert bad.status_code == 401


def test_registration_requires_email_verification(neon_client):
    neon_client.app.state.settings.require_email_verification = True
    provider = neon_client.app.state.runtime.auth
    provider.verified = False

    response = neon_client.post(
        "/auth/register",
        json={"email": "ada@example.com", "password": "correct-horse", "name": "Ada"},
    )
    assert response.status_code == 403
    assert "verification" in response.json()["detail"].lower()

    blocked = neon_client.post(
        "/auth/login",
        json={"email": "ada@example.com", "password": "correct-horse"},
    )
    assert blocked.status_code == 403

    resend = neon_client.post(
        "/auth/resend-verification", json={"email": "ada@example.com"}
    )
    assert resend.status_code == 202

    bad = neon_client.post(
        "/auth/verify-email",
        json={
            "email": "ada@example.com",
            "password": "correct-horse",
            "otp": "000000",
        },
    )
    assert bad.status_code == 401

    verified = neon_client.post(
        "/auth/verify-email",
        json={
            "email": "ada@example.com",
            "password": "correct-horse",
            "otp": "123456",
        },
    )
    assert verified.status_code == 200
    assert verified.json()["token"]
    assert verified.json()["user"]["email"] == "ada@example.com"


def test_user_data_is_isolated(neon_client):
    ada = register(neon_client, "ada@example.com")
    grace = register(neon_client, "grace@example.com")

    created = neon_client.post(
        "/meetings",
        json={"title": "Ada's meeting"},
        headers=auth_header(ada["token"]),
    )
    assert created.status_code == 200
    meeting_id = created.json()["id"]

    assert neon_client.get("/meetings", headers=auth_header(ada["token"])).json()
    assert neon_client.get("/meetings", headers=auth_header(grace["token"])).json() == []
    assert (
        neon_client.get(
            f"/meetings/{meeting_id}", headers=auth_header(grace["token"])
        ).status_code
        == 404
    )


def test_logout_revokes_only_the_current_session(neon_client):
    first = register(neon_client)
    second = neon_client.post(
        "/auth/login",
        json={"email": "ada@example.com", "password": "correct-horse"},
    ).json()

    assert neon_client.post("/auth/logout", headers=auth_header(first["token"])).status_code == 200
    assert neon_client.get("/auth/me", headers=auth_header(first["token"])).status_code == 401
    assert neon_client.get("/auth/me", headers=auth_header(second["token"])).status_code == 200


def test_expired_session_is_rejected(neon_client):
    body = register(neon_client)

    with SessionLocal() as db:
        record = db.query(SessionRecord).filter(SessionRecord.user_id == body["user"]["id"]).one()
        record.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()

    assert neon_client.get("/auth/me", headers=auth_header(body["token"])).status_code == 401


def test_invalid_token_is_rejected(neon_client):
    response = neon_client.get("/auth/me", headers=auth_header("not-a-real-token"))
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_registration_validates_input(neon_client):
    response = neon_client.post(
        "/auth/register",
        json={"email": "not-an-email", "password": "short", "name": ""},
    )
    assert response.status_code == 422


def _neon_settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "app_env": "development",
        "auth_mode": "neon",
        "ui_base_url": "https://ui.example",
        "neon_auth_base_url": "https://auth.example/neondb/auth",
        "neon_auth_jwks_url": "https://auth.example/neondb/auth/.well-known/jwks.json",
    }
    values.update(overrides)
    return Settings(**values)


def test_neon_auth_sends_the_ui_origin():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["origin"] == "https://ui.example"
        assert str(request.url) == "https://auth.example/neondb/auth/sign-up/email"
        return httpx.Response(
            200,
            json={
                "user": {
                    "id": "neon-1",
                    "email": "ada@example.com",
                    "name": "Ada",
                    "emailVerified": True,
                }
            },
        )

    provider = NeonAuthProvider(
        _neon_settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    identity = provider.register("ada@example.com", "correct-horse", "Ada")
    assert identity.id == "neon-1"
    assert identity.email == "ada@example.com"


def test_neon_auth_email_verification_otp_paths():
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"status": True})

    provider = NeonAuthProvider(
        _neon_settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    provider.send_verification_otp("ada@example.com")
    provider.verify_email_otp("ada@example.com", "123456")

    assert calls == [
        (
            "/neondb/auth/email-otp/send-verification-otp",
            {"email": "ada@example.com", "type": "email-verification"},
        ),
        (
            "/neondb/auth/email-otp/verify-email",
            {"email": "ada@example.com", "otp": "123456"},
        ),
    ]


def test_neon_auth_signup_without_verified_claim_is_unverified():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "user": {
                    "id": "neon-1",
                    "email": "ada@example.com",
                    "name": "Ada",
                }
            },
        )

    provider = NeonAuthProvider(
        _neon_settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    identity = provider.register("ada@example.com", "correct-horse", "Ada")
    assert identity.email_verified is False


def test_neon_jwt_uses_derived_issuer_and_audience():
    private_key = Ed25519PrivateKey.generate()
    now = int(datetime.now(UTC).timestamp())
    token = jwt.encode(
        {
            "sub": "neon-1",
            "email": "ada@example.com",
            "name": "Ada",
            "emailVerified": True,
            "iss": "https://auth.example",
            "aud": "https://auth.example",
            "iat": now,
            "exp": now + 900,
        },
        private_key,
        algorithm="EdDSA",
        headers={"kid": "test"},
    )
    provider = NeonAuthProvider(_neon_settings())
    provider._jwks = SimpleNamespace(
        get_signing_key_from_jwt=lambda _: SimpleNamespace(key=private_key.public_key())
    )
    identity = provider.verify_jwt(token)
    assert identity.id == "neon-1"
    assert identity.email == "ada@example.com"
    assert identity.email_verified is True


def test_neon_jwt_rejects_a_different_issuer():
    private_key = Ed25519PrivateKey.generate()
    now = int(datetime.now(UTC).timestamp())
    token = jwt.encode(
        {
            "sub": "neon-1",
            "email": "ada@example.com",
            "iss": "https://evil.example",
            "aud": "https://auth.example",
            "iat": now,
            "exp": now + 900,
        },
        private_key,
        algorithm="EdDSA",
    )
    provider = NeonAuthProvider(_neon_settings())
    provider._jwks = SimpleNamespace(
        get_signing_key_from_jwt=lambda _: SimpleNamespace(key=private_key.public_key())
    )
    with pytest.raises(AuthError):
        provider.verify_jwt(token)


def test_neon_duplicate_signup_maps_to_conflict():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "message": "User already exists. Use another email.",
                "code": "USER_ALREADY_EXISTS_USE_ANOTHER_EMAIL",
            },
        )

    provider = NeonAuthProvider(
        _neon_settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(AuthError) as caught:
        provider.register("ada@example.com", "correct-horse", "Ada")
    assert caught.value.status_code == 409
