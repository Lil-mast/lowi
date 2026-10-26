"""Transcribe, summarize, and optionally post to Discord."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import LiveSession, Meeting, PipelineRun, Recording, Transcript
from app.services.discord import send_summary
from app.services.llm import CompleteJson
from app.services.storage import Storage
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
    storage: Storage,
    force: bool = False,
) -> None:
    db = session_factory()
    run = PipelineRun(
        meeting_id=meeting_id,
        kind="pipeline",
        status="running",
        attempts=1,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    started = datetime.now(UTC)

    try:
        meeting = db.get(Meeting, meeting_id)
        if meeting is None:
            _finish_run(db, run, "failed", "meeting_missing", "Meeting no longer exists", started)
            return

        meeting.error = None
        meeting.error_code = None
        meeting.error_message = None
        recording = db.scalar(
            select(Recording)
            .where(Recording.meeting_id == meeting_id)
            .order_by(Recording.created_at.desc())
        )
        if recording is None or (not recording.storage_key and not recording.local_path):
            meeting.status = "failed"
            meeting.error = "No recording to transcribe"
            meeting.error_code = "no_recording"
            meeting.error_message = "No recording to transcribe"
            _finish_run(db, run, "failed", "no_recording", meeting.error_message, started)
            return

        try:
            payload = _transcribe(settings, storage, recording)
            _save_transcript(db, meeting, recording, payload)
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
            _finish_live_session(db, meeting_id, "completed", None, None)
            db.commit()
            db.refresh(summary)
            if settings.discord_webhook_url:
                send_summary(settings.discord_webhook_url, meeting, summary)
                meeting.status = "sent"
                db.commit()
            _finish_run(db, run, "succeeded", None, None, started)
        except Exception as exc:  # noqa: BLE001 — record any provider failure on the meeting
            db.rollback()
            failed = db.get(Meeting, meeting_id)
            if failed is not None:
                failed.status = "failed"
                failed.error = "Processing failed. Check the server logs for details."
                failed.error_code = "pipeline_failed"
                failed.error_message = str(exc)[:1000]
                _finish_live_session(db, meeting_id, "failed", "pipeline_failed", str(exc)[:1000])
                db.commit()
            _finish_run(db, run, "failed", "pipeline_failed", str(exc)[:1000], started)
    finally:
        db.close()


def _transcribe(settings: Settings, storage: Storage, recording: Recording) -> TranscriptPayload:
    if recording.storage_key:
        with storage.materialize(recording.storage_key) as path:
            return transcribe_file(settings, path)
    if recording.local_path:
        return transcribe_file(settings, Path(recording.local_path))
    raise RuntimeError("Recording has no readable location")


def _finish_run(
    db: Session,
    run: PipelineRun,
    status: str,
    error_code: str | None,
    error_message: str | None,
    started: datetime,
) -> None:
    run.status = status
    run.finished_at = datetime.now(UTC)
    run.duration_ms = int((run.finished_at - started).total_seconds() * 1000)
    run.error_code = error_code
    run.error_message = error_message
    db.commit()


def _save_transcript(
    db: Session,
    meeting: Meeting,
    recording: Recording,
    payload: TranscriptPayload,
) -> None:
    db.add(
        Transcript(
            meeting_id=meeting.id,
            raw_text=payload.raw_text,
            diarized_json=payload.diarized_json,
            language=payload.language,
            source="live_batch" if recording.source == "live" else "upload",
            word_count=len(payload.raw_text.split()),
        )
    )
    meeting.status = "transcribed"
    db.commit()


def _finish_live_session(
    db: Session,
    meeting_id: str,
    status: str,
    error_code: str | None,
    error_message: str | None,
) -> None:
    live_session = db.scalar(
        select(LiveSession)
        .where(LiveSession.meeting_id == meeting_id, LiveSession.status == "finalizing")
        .order_by(LiveSession.created_at.desc())
    )
    if live_session is None:
        return
    live_session.status = status
    live_session.ended_at = datetime.now(UTC)
    live_session.error_code = error_code
    live_session.error_message = error_message
