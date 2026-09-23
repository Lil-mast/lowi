"""Shared FastAPI dependencies."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Meeting, User
from app.db.session import get_db, seed_default_user


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_current_user(
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> User:
    return seed_default_user(db, settings)


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
