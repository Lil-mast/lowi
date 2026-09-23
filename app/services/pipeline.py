"""Transcribe, summarize, and optionally post to Discord."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import Meeting, Recording, Transcript
from app.services.discord import send_summary
from app.services.llm import CompleteJson
from app.services.summarizer import (
    latest_transcript,
    store_summary,
    summarize_transcript,
)
from app.services.transcription import TranscriptPayload, transcribe_file


def run_pipeline(
    meeting_id: str,
    session_factory: sessionmaker[Session],
    settings: Settings,
    complete_json: CompleteJson,
) -> None:
    db = session_factory()
    try:
        meeting = db.get(Meeting, meeting_id)
        if meeting is None:
            return
        meeting.error = None
        recording = db.scalar(
            select(Recording)
            .where(Recording.meeting_id == meeting_id)
            .order_by(Recording.created_at.desc())
        )
        if recording is None or not recording.local_path:
            meeting.status = "failed"
            meeting.error = "No recording to transcribe"
            db.commit()
            return
        try:
            payload = transcribe_file(settings, Path(recording.local_path))
            _save_transcript(db, meeting, payload)
            transcript = latest_transcript(db, meeting.id)
            if transcript is None:
                raise RuntimeError("Transcript was not stored")
            structured = summarize_transcript(
                settings,
                meeting.title,
                transcript.raw_text,
                complete_json,
            )
            summary = store_summary(db, meeting, structured)
            meeting.status = "summarized"
            db.commit()
            db.refresh(summary)
            if settings.discord_webhook_url:
                send_summary(settings.discord_webhook_url, meeting, summary)
                meeting.status = "sent"
                db.commit()
        except Exception as exc:  # noqa: BLE001 — record any provider failure on the meeting
            db.rollback()
            failed = db.get(Meeting, meeting_id)
            if failed is not None:
                failed.status = "failed"
                failed.error = str(exc)
                db.commit()
    finally:
        db.close()


def _save_transcript(db: Session, meeting: Meeting, payload: TranscriptPayload) -> None:
    db.add(
        Transcript(
            meeting_id=meeting.id,
            raw_text=payload.raw_text,
            diarized_json=payload.diarized_json,
            language=payload.language,
        )
    )
    meeting.status = "transcribed"
    db.commit()
