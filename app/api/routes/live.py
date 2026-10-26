"""Live meeting capture: short-lived tickets and the audio WebSocket proxy."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.api.deps import get_current_user, get_meeting, get_settings
from app.config import Settings
from app.db.models import LiveSegment, LiveSession, Meeting, User
from app.db.session import SessionLocal
from app.schemas.live import LiveTicketOut
from app.services.live import (
    LiveTicketError,
    create_live_ticket,
    finalize_live_session,
    live_ws_url,
    verify_live_ticket,
)
from app.services.realtime import RealtimeError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["live"])

ERROR_EVENTS = {
    "auth_error",
    "quota_exceeded",
    "transcriber_error",
    "input_error",
    "invalid_request",
    "error",
    "commit_throttled",
    "unaccepted_terms",
    "rate_limited",
    "queue_overflow",
    "resource_exhausted",
    "session_time_limit_exceeded",
    "chunk_size_exceeded",
    "insufficient_audio_activity",
}


@router.post("/meetings/{meeting_id}/live/ticket", response_model=LiveTicketOut)
def create_ticket(
    meeting: Meeting = Depends(get_meeting),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> LiveTicketOut:
    ticket, expires_at = create_live_ticket(settings, meeting.id, user.id)
    return LiveTicketOut(
        ticket=ticket,
        ws_url=live_ws_url(settings, meeting.id, ticket),
        expires_at=expires_at,
    )


@router.websocket("/meetings/{meeting_id}/live")
async def live_websocket(
    websocket: WebSocket,
    meeting_id: str,
    ticket: str = Query(default=""),
) -> None:
    settings: Settings = websocket.app.state.settings
    runtime = websocket.app.state.runtime

    try:
        user_id = verify_live_ticket(settings, ticket, meeting_id)
    except LiveTicketError as exc:
        await websocket.close(code=4401, reason=str(exc))
        return

    with SessionLocal() as db:
        meeting = db.scalar(
            select(Meeting).where(Meeting.id == meeting_id, Meeting.user_id == user_id)
        )
        if meeting is None:
            await websocket.close(code=4404)
            return
        source = websocket.query_params.get("source", "mic")
        if source not in {"mic", "tab"}:
            source = "mic"
        live_session = LiveSession(
            meeting_id=meeting.id,
            user_id=user_id,
            status="recording",
            source=source,
            started_at=datetime.now(UTC),
        )
        db.add(live_session)
        db.commit()
        db.refresh(live_session)
        session_id = live_session.id

    await websocket.accept()
    await websocket.send_json({"type": "connecting", "session_id": session_id})

    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        pcm_handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - kept open for the session
            suffix=".pcm", delete=False, dir=settings.data_dir
        )
        pcm_path = Path(pcm_handle.name)
    except Exception as exc:
        logger.exception("Could not create the live audio file for %s", session_id)
        _mark_session_failed(session_id, "live_storage_failed", str(exc)[:1000])
        with suppress(Exception):
            await websocket.send_json(
                {"type": "error", "code": "storage_failed", "message": "Could not store live audio"}
            )
        with suppress(Exception):
            await websocket.close(code=1011)
        return
    started = datetime.now(UTC)
    parts: list[str] = []
    segments: list[dict] = []
    last_partial = {"text": ""}
    audio_bytes = 0
    max_bytes = settings.live_max_minutes * 60 * 16000 * 2
    reason = "disconnect"
    stop_event = asyncio.Event()

    try:
        async with runtime.realtime.connect() as upstream:
            await websocket.send_json({"type": "ready", "session_id": session_id})
            receiver = asyncio.create_task(
                _receive_from_elevenlabs(
                    upstream,
                    websocket,
                    session_id,
                    meeting_id,
                    parts,
                    segments,
                    last_partial,
                    stop_event,
                )
            )
            try:
                reason, audio_bytes = await _receive_from_browser(
                    websocket,
                    upstream,
                    pcm_handle,
                    max_bytes,
                )
            except (WebSocketDisconnect, RuntimeError):
                reason = "disconnect"
            finally:
                if reason == "stop":
                    # Commit the tail, then give Scribe a moment to emit the
                    # final committed transcript. Do not return after the
                    # first event: a pending VAD commit may arrive first.
                    stop_event.set()
                    with suppress(Exception):
                        await _send_audio(upstream, b"\x00\x00" * 1600, commit=True)
                        with suppress(asyncio.TimeoutError):
                            await asyncio.wait_for(receiver, timeout=3.5)
                receiver.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await receiver
    except RealtimeError as exc:
        logger.warning("Realtime connection failed for %s: %s", meeting_id, exc)
        with suppress(Exception):
            await websocket.send_json(
                {"type": "error", "code": "realtime_unavailable", "message": str(exc)}
            )
        reason = "error"
    except Exception:
        logger.exception("Live session %s failed", session_id)
        reason = "error"
    finally:
        pcm_handle.close()
        duration = (datetime.now(UTC) - started).total_seconds()

    if reason == "error":
        _mark_session_failed(session_id, "live_failed", "Live capture failed")
        with suppress(Exception):
            await websocket.close(code=1011)
        pcm_path.unlink(missing_ok=True)
        return

    if not parts and last_partial["text"].strip():
        parts.append(last_partial["text"].strip())
        segments.append({"sequence": 1, "text": last_partial["text"].strip()})

    with suppress(Exception):
        await websocket.send_json({"type": "finalizing", "session_id": session_id})
    try:
        await finalize_live_session(
            session_id=session_id,
            meeting_id=meeting_id,
            settings=settings,
            storage=runtime.storage,
            queue=runtime.queue,
            pcm_path=pcm_path,
            transcript_text=" ".join(parts).strip(),
            segments=segments,
            duration_seconds=duration,
            audio_bytes=audio_bytes,
        )
        with suppress(Exception):
            await websocket.send_json({"type": "stopped", "session_id": session_id})
    except Exception as exc:
        logger.exception("Could not finalize live session %s", session_id)
        _mark_session_failed(session_id, "live_finalize_failed", str(exc)[:1000])
        with suppress(Exception):
            await websocket.send_json(
                {"type": "error", "code": "finalize_failed", "message": "Could not save the recording"}
            )
    finally:
        pcm_path.unlink(missing_ok=True)
        with suppress(Exception):
            await websocket.close()


async def _receive_from_browser(
    websocket: WebSocket,
    upstream: Any,
    pcm_handle: Any,
    max_bytes: int,
) -> tuple[str, int]:
    audio_bytes = 0
    while True:
        message = await websocket.receive()
        if message.get("type") == "websocket.disconnect":
            return "disconnect", audio_bytes

        chunk = message.get("bytes")
        if chunk:
            audio_bytes += len(chunk)
            if audio_bytes > max_bytes:
                with suppress(Exception):
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "too_large",
                            "message": "Live session exceeded the duration limit",
                        }
                    )
                return "too_large", audio_bytes
            pcm_handle.write(chunk)
            await _send_audio(upstream, chunk, commit=False)
            continue

        raw = message.get("text")
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except ValueError:
            continue
        if payload.get("type") == "stop":
            return "stop", audio_bytes
        if payload.get("type") == "ping":
            with suppress(Exception):
                await websocket.send_json({"type": "pong"})


async def _send_audio(upstream: Any, chunk: bytes, *, commit: bool) -> None:
    payload = {
        "message_type": "input_audio_chunk",
        "audio_base_64": base64.b64encode(chunk).decode("ascii"),
        "commit": commit,
        "sample_rate": 16000,
    }
    await upstream.send(json.dumps(payload))


async def _receive_from_elevenlabs(
    upstream: Any,
    websocket: WebSocket,
    session_id: str,
    meeting_id: str,
    parts: list[str],
    segments: list[dict],
    last_partial: dict[str, str],
    stop_event: asyncio.Event,
) -> None:
    sequence = len(segments)
    try:
        while True:
            raw = await upstream.recv()
            try:
                event = json.loads(raw)
            except (ValueError, TypeError):
                continue
            event_type = event.get("message_type")

            if event_type == "session_started":
                with suppress(Exception):
                    await websocket.send_json(
                        {"type": "upstream_ready", "provider_session_id": event.get("session_id")}
                    )
            elif event_type == "partial_transcript":
                text = str(event.get("text") or "")
                last_partial["text"] = text
                with suppress(Exception):
                    await websocket.send_json({"type": "partial", "text": text})
            elif event_type == "committed_transcript":
                text = str(event.get("text") or "").strip()
                if text:
                    sequence += 1
                    parts.append(text)
                    segment = {"sequence": sequence, "text": text}
                    segments.append(segment)
                    await asyncio.to_thread(
                        _store_segment, session_id, meeting_id, sequence, text
                    )
                    with suppress(Exception):
                        await websocket.send_json(
                            {
                                "type": "final",
                                "text": text,
                                "sequence": sequence,
                                "words": event.get("words"),
                            }
                        )
            elif event_type == "committed_transcript_with_timestamps":
                # Sent after committed_transcript when timestamps are enabled.
                # LoWi disables timestamps to avoid storing each segment twice.
                continue
            elif event_type in ERROR_EVENTS:
                message = str(event.get("error") or event_type)
                logger.warning("ElevenLabs realtime error %s: %s", event_type, message)
                with suppress(Exception):
                    await websocket.send_json(
                        {"type": "error", "code": event_type, "message": message}
                    )
                with suppress(Exception):
                    await websocket.close(code=1011)
                return
    except asyncio.CancelledError:
        raise
    except Exception:
        if stop_event.is_set():
            logger.info("Realtime connection closed while finalizing %s", session_id)
            return
        logger.exception("Realtime receiver failed for %s", session_id)
        with suppress(Exception):
            await websocket.send_json(
                {"type": "error", "code": "realtime_disconnected", "message": "Transcription connection ended"}
            )
        with suppress(Exception):
            await websocket.close(code=1011)


def _store_segment(
    session_id: str,
    meeting_id: str,
    sequence: int,
    text: str,
) -> None:
    with SessionLocal() as db:
        db.add(
            LiveSegment(
                live_session_id=session_id,
                meeting_id=meeting_id,
                sequence=sequence,
                text=text,
                is_final=True,
            )
        )
        db.commit()


def _mark_session_failed(session_id: str, code: str, message: str) -> None:
    with SessionLocal() as db:
        live_session = db.get(LiveSession, session_id)
        if live_session is None:
            return
        live_session.status = "failed"
        live_session.ended_at = datetime.now(UTC)
        live_session.error_code = code
        live_session.error_message = message
        db.commit()
