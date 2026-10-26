"""Local user records linked to an external identity provider."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User
from app.services.auth import AuthIdentity


def upsert_auth_user(db: Session, identity: AuthIdentity) -> User:
    """Resolve a Neon Auth identity to a local user, linking legacy emails."""
    user = db.scalar(
        select(User).where(User.neon_auth_user_id == identity.id)
    )
    if user is None:
        user = db.scalar(select(User).where(User.email == identity.email))
    if user is None:
        user = User(
            email=identity.email,
            name=identity.name,
            neon_auth_user_id=identity.id,
        )
        db.add(user)
    else:
        user.neon_auth_user_id = identity.id
        if identity.name:
            user.name = identity.name
        if identity.email:
            user.email = identity.email

    user.last_login_at = datetime.now(UTC)
    db.commit()
    db.refresh(user)
    return user
