"""Authentication endpoints backed by Neon Auth."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_auth_provider,
    get_bearer_token,
    get_current_user,
    get_settings,
)
from app.config import Settings
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import (
    AuthConfigOut,
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    ResendVerificationRequest,
    UserOut,
    VerifyEmailRequest,
)
from app.services.auth import AuthError, AuthProvider
from app.services.sessions import create_session, revoke_session
from app.services.users import upsert_auth_user

router = APIRouter(prefix="/auth", tags=["auth"])


def _response(
    token: str,
    expires_at: datetime,
    user: User,
) -> AuthResponse:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return AuthResponse(token=token, expires_at=expires_at, user=UserOut.model_validate(user))


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    return request.headers.get("user-agent"), ip


@router.get("/config", response_model=AuthConfigOut)
def auth_config(settings: Settings = Depends(get_settings)) -> AuthConfigOut:
    return AuthConfigOut(
        email=True,
        google=settings.google_oauth_enabled,
        required=settings.auth_mode == "neon",
        email_verification=settings.require_email_verification,
    )


@router.post("/register", response_model=AuthResponse)
def register(
    body: RegisterRequest,
    request: Request,
    provider: AuthProvider = Depends(get_auth_provider),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> AuthResponse:
    if provider is None:
        raise HTTPException(status_code=400, detail="Authentication is disabled")
    try:
        identity = provider.register(str(body.email), body.password, body.name)
        if settings.require_email_verification and not identity.email_verified:
            raise AuthError(
                "Check your email for a verification code, then verify it to continue.",
                403,
            )
        user = upsert_auth_user(db, identity)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    user_agent, ip = _client_meta(request)
    token, record = create_session(
        db,
        user,
        ttl_days=settings.session_ttl_days,
        user_agent=user_agent,
        ip=ip,
    )
    return _response(token, record.expires_at, user)


@router.post("/login", response_model=AuthResponse)
def login(
    body: LoginRequest,
    request: Request,
    provider: AuthProvider = Depends(get_auth_provider),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> AuthResponse:
    if provider is None:
        raise HTTPException(status_code=400, detail="Authentication is disabled")
    try:
        identity = provider.login(str(body.email), body.password)
        if settings.require_email_verification and not identity.email_verified:
            raise AuthError("Verify your email before signing in.", 403)
        user = upsert_auth_user(db, identity)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    user_agent, ip = _client_meta(request)
    token, record = create_session(
        db,
        user,
        ttl_days=settings.session_ttl_days,
        user_agent=user_agent,
        ip=ip,
    )
    return _response(token, record.expires_at, user)


@router.post("/verify-email", response_model=AuthResponse)
def verify_email(
    body: VerifyEmailRequest,
    request: Request,
    provider: AuthProvider = Depends(get_auth_provider),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> AuthResponse:
    if provider is None:
        raise HTTPException(status_code=400, detail="Authentication is disabled")
    try:
        provider.verify_email_otp(str(body.email), body.otp)
        identity = provider.login(str(body.email), body.password)
        if settings.require_email_verification and not identity.email_verified:
            raise AuthError("Email verification failed", 403)
        user = upsert_auth_user(db, identity)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    user_agent, ip = _client_meta(request)
    token, record = create_session(
        db,
        user,
        ttl_days=settings.session_ttl_days,
        user_agent=user_agent,
        ip=ip,
    )
    return _response(token, record.expires_at, user)


@router.post("/resend-verification", status_code=status.HTTP_202_ACCEPTED)
def resend_verification(
    body: ResendVerificationRequest,
    provider: AuthProvider = Depends(get_auth_provider),
) -> dict[str, str]:
    if provider is None:
        raise HTTPException(status_code=400, detail="Authentication is disabled")
    try:
        provider.send_verification_otp(str(body.email))
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {"status": "sent"}


@router.post("/logout")
def logout(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    token = get_bearer_token(request)
    if token is not None:
        revoke_session(db, token)
    return {"status": "signed_out"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
