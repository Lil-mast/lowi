"""Opaque LoWi session tokens."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Session as SessionRecord
from app.db.models import User


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def create_session(
    db: Session,
    user: User,
    *,
    ttl_days: int,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[str, SessionRecord]:
    token = secrets.token_urlsafe(32)
    record = SessionRecord(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=datetime.now(UTC) + timedelta(days=ttl_days),
        user_agent=(user_agent or "")[:500] or None,
        ip=(ip or "")[:64] or None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return token, record


def resolve_session(db: Session, token: str) -> User | None:
    record = db.scalar(select(SessionRecord).where(SessionRecord.token_hash == hash_token(token)))
    if record is None:
        return None

    now = datetime.now(UTC)
    if _as_utc(record.expires_at) <= now:
        db.delete(record)
        db.commit()
        return None

    user = db.get(User, record.user_id)
    if user is None:
        db.delete(record)
        db.commit()
        return None

    last_seen = record.last_seen_at
    if last_seen is None or now - _as_utc(last_seen) > timedelta(minutes=5):
        record.last_seen_at = now
        db.commit()

    return user


def revoke_session(db: Session, token: str) -> None:
    db.execute(delete(SessionRecord).where(SessionRecord.token_hash == hash_token(token)))
    db.commit()


def delete_expired_sessions(db: Session) -> int:
    result = db.execute(
        delete(SessionRecord).where(SessionRecord.expires_at <= datetime.now(UTC))
    )
    db.commit()
    return int(result.rowcount or 0)
