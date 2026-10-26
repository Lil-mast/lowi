"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Meeting, User
from app.db.session import get_db, seed_user
from app.services.auth import AuthError, AuthProvider
from app.services.sessions import resolve_session
from app.services.users import upsert_auth_user


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_auth_provider(request: Request) -> AuthProvider:
    provider = getattr(request.app.state.runtime, "auth", None)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication provider is not configured",
        )
    return provider


def get_bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def get_current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> User:
    if settings.auth_mode == "test":
        return seed_user(db, settings.test_user_email, settings.test_user_name)
    if settings.auth_mode == "dev":
        return seed_user(db, settings.default_user_email, settings.default_user_name)

    token = get_bearer_token(request)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = resolve_session(db, token)
    if user is not None:
        return user

    provider = get_auth_provider(request)
    try:
        identity = provider.verify_jwt(token)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=exc.message,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return upsert_auth_user(db, identity)


def get_meeting(
    meeting_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Meeting:
    meeting = db.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.user_id == user.id)
    )
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting
