"""Transcript endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_meeting
from app.db.models import Meeting
from app.db.session import get_db
from app.schemas.meetings import TranscriptOut
from app.services.summarizer import latest_transcript

router = APIRouter(tags=["transcripts"])


@router.get("/meetings/{meeting_id}/transcript", response_model=TranscriptOut)
def read_transcript(
    meeting: Meeting = Depends(get_meeting),
    db: Session = Depends(get_db),
) -> TranscriptOut:
    transcript = latest_transcript(db, meeting.id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return TranscriptOut.model_validate(transcript)
