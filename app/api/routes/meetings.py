"""Meeting endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_meeting, get_settings
from app.db.models import ActionItem, Meeting, Recording, Summary, User, new_id
from app.db.session import get_db
from app.schemas.meetings import (
    ActionItemOut,
    MeetingCreate,
    MeetingDetail,
    MeetingOut,
    SummaryOut,
    TranscriptOut,
)
from app.services.discord import send_summary
from app.services.jobs import pipeline_job_id
from app.services.pdf import render_summary_pdf
from app.services.prep import build_prep_context, generate_prep
from app.services.storage import (
    StorageError,
    UploadTooLarge,
    audio_key,
    store_upload,
)
from app.services.summarizer import (
    latest_transcript,
    store_summary,
    summarize_transcript,
)

ALLOWED_AUDIO_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
}

router = APIRouter(tags=["meetings"])


def meeting_detail(db: Session, meeting: Meeting) -> MeetingDetail:
    transcript = latest_transcript(db, meeting.id)
    summary = db.scalar(
        select(Summary).where(Summary.meeting_id == meeting.id).order_by(Summary.created_at.desc())
    )
    items = db.scalars(
        select(ActionItem).where(ActionItem.meeting_id == meeting.id).order_by(ActionItem.created_at)
    ).all()
    return MeetingDetail(
        **MeetingOut.model_validate(meeting).model_dump(),
        transcript=TranscriptOut.model_validate(transcript) if transcript else None,
        summary=SummaryOut.model_validate(summary) if summary else None,
        action_items=[ActionItemOut.model_validate(item) for item in items],
    )


@router.post("/meetings", response_model=MeetingDetail)
def create_meeting(
    body: MeetingCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings=Depends(get_settings),
) -> MeetingDetail:
    meeting = Meeting(
        user_id=user.id,
        title=body.title,
        scheduled_at=body.scheduled_at,
        calendar_event_id=body.calendar_event_id,
        agenda=body.agenda,
        attendees=[attendee.model_dump() for attendee in body.attendees] or None,
        project=body.project,
        status="scheduled",
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    if body.generate_prep:
        try:
            context = build_prep_context(db, user.id, body.title, body.agenda)
            meeting.prep_brief = generate_prep(
                settings, context, request.app.state.runtime.complete_json
            )
            db.commit()
            db.refresh(meeting)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    return meeting_detail(db, meeting)


@router.get("/meetings", response_model=list[MeetingOut])
def list_meetings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Meeting]:
    return list(
        db.scalars(
            select(Meeting).where(Meeting.user_id == user.id).order_by(Meeting.created_at.desc())
        ).all()
    )


@router.get("/meetings/{meeting_id}", response_model=MeetingDetail)
def read_meeting(
    meeting: Meeting = Depends(get_meeting),
    db: Session = Depends(get_db),
) -> MeetingDetail:
    return meeting_detail(db, meeting)


@router.post("/meetings/{meeting_id}/upload")
async def upload_audio(
    request: Request,
    meeting: Meeting = Depends(get_meeting),
    db: Session = Depends(get_db),
    settings=Depends(get_settings),
    file: UploadFile = File(...),
) -> dict[str, str]:
    filename = file.filename or "audio.bin"
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported audio format")

    queue = request.app.state.runtime.queue
    storage = request.app.state.runtime.storage
    if queue is None:
        raise HTTPException(status_code=503, detail="Job queue is not configured")

    recording_id = new_id()
    key = audio_key(meeting.id, recording_id, filename)
    try:
        stored = await asyncio.to_thread(
            store_upload,
            storage,
            key,
            file.file,
            content_type=file.content_type or "application/octet-stream",
            max_bytes=settings.max_upload_mb * 1024 * 1024,
        )
    except UploadTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db.add(
        Recording(
            id=recording_id,
            meeting_id=meeting.id,
            storage_backend=stored.backend,
            storage_key=stored.key,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            checksum_sha256=stored.checksum_sha256,
            source="upload",
            status="stored",
        )
    )
    meeting.status = "uploaded"
    meeting.error = None
    meeting.error_code = None
    meeting.error_message = None
    meeting.pipeline_version = (meeting.pipeline_version or 1) + 1
    db.commit()

    job_id = pipeline_job_id(meeting.id, meeting.pipeline_version)
    await queue.enqueue(
        "pipeline",
        {"meeting_id": meeting.id, "force": True},
        job_id=job_id,
        max_tries=3,
    )
    return {
        "meeting_id": meeting.id,
        "status": "uploaded",
        "recording_id": recording_id,
        "job_id": job_id,
    }


@router.post("/meetings/{meeting_id}/summarize", response_model=MeetingDetail)
def summarize_meeting(
    request: Request,
    meeting: Meeting = Depends(get_meeting),
    db: Session = Depends(get_db),
    settings=Depends(get_settings),
) -> MeetingDetail:
    transcript = latest_transcript(db, meeting.id)
    if transcript is None:
        raise HTTPException(status_code=409, detail="Meeting has no transcript")
    try:
        structured = summarize_transcript(
            settings,
            meeting.title,
            transcript.raw_text,
            request.app.state.runtime.complete_json,
        )
        store_summary(db, meeting, structured)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    meeting.status = "summarized"
    meeting.error = None
    db.commit()
    db.refresh(meeting)
    return meeting_detail(db, meeting)


@router.get("/meetings/{meeting_id}/pdf")
def download_pdf(
    meeting: Meeting = Depends(get_meeting),
    db: Session = Depends(get_db),
) -> Response:
    summary = db.scalar(
        select(Summary).where(Summary.meeting_id == meeting.id).order_by(Summary.created_at.desc())
    )
    if summary is None:
        raise HTTPException(status_code=404, detail="Meeting has no summary")
    pdf = render_summary_pdf(meeting, summary)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{meeting.id}.pdf"'},
    )


@router.post("/meetings/{meeting_id}/send-discord")
def post_discord(
    meeting: Meeting = Depends(get_meeting),
    db: Session = Depends(get_db),
    settings=Depends(get_settings),
) -> dict[str, str]:
    summary = db.scalar(
        select(Summary).where(Summary.meeting_id == meeting.id).order_by(Summary.created_at.desc())
    )
    if summary is None:
        raise HTTPException(status_code=409, detail="Meeting has no summary")
    try:
        send_summary(settings.discord_webhook_url, meeting, summary)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    meeting.status = "sent"
    meeting.error = None
    db.commit()
    return {"meeting_id": meeting.id, "status": "sent"}


@router.get("/action-items", response_model=list[ActionItemOut])
def list_action_items(
    status: str = "open",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ActionItem]:
    query = select(ActionItem).join(Meeting).where(Meeting.user_id == user.id)
    if status:
        query = query.where(ActionItem.status == status)
    return list(db.scalars(query.order_by(ActionItem.created_at.desc())).all())
