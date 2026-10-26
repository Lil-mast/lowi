"""Live capture tickets and finalization."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import tempfile
import time
import wave
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import LiveSession, Meeting, Recording, Transcript, new_id
from app.db.session import SessionLocal
from app.services.jobs import JobQueue, pipeline_job_id
from app.services.storage import Storage, StorageError, audio_key


class LiveTicketError(Exception):
    """The live ticket is missing, expired, or invalid."""


def create_live_ticket(settings: Settings, meeting_id: str, user_id: str) -> tuple[str, datetime]:
    expires = int(time.time()) + settings.live_ticket_ttl_seconds
    payload = f"{meeting_id}:{user_id}:{expires}"
    signature = _signature(settings, payload)
    return f"{payload}:{signature}", datetime.fromtimestamp(expires, UTC)


def verify_live_ticket(settings: Settings, ticket: str, meeting_id: str) -> str:
    try:
        payload, signature = ticket.rsplit(":", 1)
        ticket_meeting, user_id, expires_raw = payload.split(":")
        expires = int(expires_raw)
    except (ValueError, TypeError) as exc:
        raise LiveTicketError("Invalid live ticket") from exc

    if not hmac.compare_digest(signature, _signature(settings, payload)):
        raise LiveTicketError("Invalid live ticket")
    if expires < int(time.time()):
        raise LiveTicketError("Live ticket has expired")
    if ticket_meeting != meeting_id:
        raise LiveTicketError("Live ticket is for a different meeting")
    return user_id


def live_ws_url(settings: Settings, meeting_id: str, ticket: str) -> str:
    base = settings.public_base_url.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base.removeprefix("https://")
    elif base.startswith("http://"):
        base = "ws://" + base.removeprefix("http://")
    return f"{base}/meetings/{meeting_id}/live?ticket={quote(ticket, safe='')}"


def _signature(settings: Settings, payload: str) -> str:
    digest = hmac.new(
        settings.secret_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


async def finalize_live_session(
    *,
    session_id: str,
    meeting_id: str,
    settings: Settings,
    storage: Storage,
    queue: JobQueue,
    pcm_path: Path,
    transcript_text: str,
    segments: list[dict],
    duration_seconds: float,
    audio_bytes: int,
) -> None:
    """Store captured audio, save the live transcript, and queue batch diarization."""
    wav_path: Path | None = None
    stored_key: str | None = None
    committed = False
    try:
        if not pcm_path.exists() or audio_bytes <= 0:
            _mark_failed(session_id, "no_audio", "No audio was captured")
            return

        with SessionLocal() as db:
            live_session = db.get(LiveSession, session_id)
            meeting = db.get(Meeting, meeting_id)
            if live_session is None or meeting is None:
                return
            if live_session.status != "recording":
                return
            owner_meeting_id = meeting.id

        settings.data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            suffix=".wav", delete=False, dir=settings.data_dir
        ) as handle:
            wav_path = Path(handle.name)
        await asyncio.to_thread(_pcm_to_wav, pcm_path, wav_path)

        recording_id = new_id()
        stored_key = audio_key(owner_meeting_id, recording_id, "live.wav")
        stored = await asyncio.to_thread(
            _upload_wav,
            storage,
            stored_key,
            wav_path,
            settings.max_upload_mb * 1024 * 1024,
        )

        with SessionLocal() as db:
            live_session = db.get(LiveSession, session_id)
            meeting = db.get(Meeting, owner_meeting_id)
            if live_session is None or meeting is None or live_session.status != "recording":
                _delete_quietly(storage, stored_key)
                return
            db.add(
                Recording(
                    id=recording_id,
                    meeting_id=meeting.id,
                    storage_backend=stored.backend,
                    storage_key=stored.key,
                    content_type=stored.content_type,
                    size_bytes=stored.size_bytes,
                    checksum_sha256=stored.checksum_sha256,
                    source="live",
                    duration_seconds=duration_seconds,
                    status="stored",
                )
            )
            db.add(
                Transcript(
                    meeting_id=meeting.id,
                    raw_text=transcript_text.strip(),
                    source="live",
                    live_session_id=session_id,
                    diarized_json={"segments": segments} if segments else None,
                    word_count=len(transcript_text.split()),
                )
            )
            meeting.status = "transcribed"
            meeting.error = None
            meeting.error_code = None
            meeting.error_message = None
            meeting.pipeline_version = (meeting.pipeline_version or 1) + 1
            live_session.status = "finalizing"
            live_session.ended_at = datetime.now(UTC)
            live_session.duration_seconds = duration_seconds
            live_session.audio_bytes = audio_bytes
            version = meeting.pipeline_version
            db.commit()
            committed = True

        await queue.enqueue(
            "pipeline",
            {"meeting_id": meeting_id, "force": True},
            job_id=pipeline_job_id(meeting_id, version),
            max_tries=3,
            wait=False,
        )
    except Exception as exc:
        if stored_key is not None and not committed:
            _delete_quietly(storage, stored_key)
        _mark_failed(session_id, "live_finalize_failed", str(exc)[:1000])
        raise
    finally:
        pcm_path.unlink(missing_ok=True)
        if wav_path is not None:
            wav_path.unlink(missing_ok=True)


def _pcm_to_wav(pcm_path: Path, wav_path: Path) -> None:
    with pcm_path.open("rb") as source_file, wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        while chunk := source_file.read(1024 * 1024):
            wav.writeframes(chunk[: len(chunk) // 2 * 2])


def _delete_quietly(storage: Storage, key: str) -> None:
    with suppress(Exception):
        storage.delete(key)


def _upload_wav(
    storage: Storage,
    key: str,
    wav_path: Path,
    max_bytes: int,
) -> Any:
    if wav_path.stat().st_size > max_bytes:
        raise StorageError("Recording exceeds the upload limit")
    with wav_path.open("rb") as upload:
        return storage.put(key, upload, "audio/wav")


def _mark_failed(session_id: str, code: str, message: str) -> None:
    with SessionLocal() as db:
        live_session = db.get(LiveSession, session_id)
        if live_session is None:
            return
        live_session.status = "failed"
        live_session.ended_at = datetime.now(UTC)
        live_session.error_code = code
        live_session.error_message = message
        db.commit()


def latest_live_session(db: Session, meeting_id: str) -> LiveSession | None:
    return db.scalar(
        select(LiveSession)
        .where(LiveSession.meeting_id == meeting_id)
        .order_by(LiveSession.created_at.desc())
    )
