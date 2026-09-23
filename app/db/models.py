"""SQLAlchemy models for meetings, transcripts, and action items."""

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    discord_webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    meetings: Mapped[list[Meeting]] = relationship(back_populates="user")


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(500))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="scheduled")
    calendar_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prep_brief: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="meetings")
    recordings: Mapped[list[Recording]] = relationship(back_populates="meeting")
    transcripts: Mapped[list[Transcript]] = relationship(back_populates="meeting")
    summaries: Mapped[list[Summary]] = relationship(back_populates="meeting")
    action_items: Mapped[list[ActionItem]] = relationship(back_populates="meeting")


class Recording(Base):
    __tablename__ = "recordings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"))
    local_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="stored")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    meeting: Mapped[Meeting] = relationship(back_populates="recordings")


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"))
    raw_text: Mapped[str] = mapped_column(Text, default="")
    diarized_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    meeting: Mapped[Meeting] = relationship(back_populates="transcripts")


class Summary(Base):
    __tablename__ = "summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"))
    structured_json: Mapped[dict] = mapped_column(JSON)
    narrative: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    meeting: Mapped[Meeting] = relationship(back_populates="summaries")


class ActionItem(Base):
    __tablename__ = "action_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"))
    description: Mapped[str] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    meeting: Mapped[Meeting] = relationship(back_populates="action_items")
