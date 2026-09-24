"""Request and response models for meetings."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


# MeetingCreate is the request model for creating a meeting.
class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    scheduled_at: datetime | None = None
    calendar_event_id: str | None = None
    agenda: str | None = Field(default=None, max_length=8000)
    generate_prep: bool = False


# ActionItemOut is the response model for an action item.
class ActionItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    meeting_id: str
    description: str
    owner: str | None
    due_date: date | None
    status: str


class TranscriptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    raw_text: str
    diarized_json: dict | list | None
    language: str | None


class SummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    structured_json: dict
    narrative: str


class MeetingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    scheduled_at: datetime | None
    status: str
    calendar_event_id: str | None
    agenda: str | None
    prep_brief: str | None
    error: str | None
    created_at: datetime


# MeetingDetail is the response model for a meeting with its transcript, summary, and action items.
class MeetingDetail(MeetingOut):
    transcript: TranscriptOut | None = None
    summary: SummaryOut | None = None
    action_items: list[ActionItemOut] = []
