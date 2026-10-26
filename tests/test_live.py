from __future__ import annotations

import asyncio
import io
import json
import wave
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from app.config import Settings
from app.db.models import LiveSession, Meeting, Recording, Transcript, User
from app.db.session import SessionLocal, configure_engine, init_db
from app.services.live import (
    LiveTicketError,
    create_live_ticket,
    finalize_live_session,
    live_ws_url,
    verify_live_ticket,
)
from app.services.storage import LocalStorage
from sqlalchemy import select


class FakeQueue:
    def __init__(self) -> None:
        self.jobs: list[dict] = []

    async def enqueue(self, kind, payload, *, job_id, max_tries=3, wait=True):
        self.jobs.append(
            {
                "kind": kind,
                "payload": payload,
                "job_id": job_id,
                "max_tries": max_tries,
                "wait": wait,
            }
        )
        return job_id


class FakeUpstream:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[dict] = []
        self.closed = False
        self.queue.put_nowait(json.dumps({"message_type": "session_started", "session_id": "p1"}))

    async def send(self, raw: str) -> None:
        payload = json.loads(raw)
        self.sent.append(payload)
        if payload.get("commit"):
            await self.queue.put(
                json.dumps(
                    {"message_type": "committed_transcript", "text": "Hello live"}
                )
            )
            self.closed = True
        elif payload.get("audio_base_64"):
            await self.queue.put(
                json.dumps({"message_type": "partial_transcript", "text": "Hello"})
            )

    async def recv(self) -> str:
        if self.closed and self.queue.empty():
            raise ConnectionError("upstream closed")
        return await self.queue.get()


class FakeRealtime:
    def __init__(self) -> None:
        self.upstream: FakeUpstream | None = None

    @asynccontextmanager
    async def connect(self):
        self.upstream = FakeUpstream()
        yield self.upstream


def test_live_ticket_round_trip():
    settings = Settings(_env_file=None, secret_key="ticket-secret", live_ticket_ttl_seconds=900)
    ticket, expires = create_live_ticket(settings, "meeting-1", "user-1")
    assert verify_live_ticket(settings, ticket, "meeting-1") == "user-1"
    assert expires > datetime.now(UTC)

    with pytest.raises(LiveTicketError, match="different meeting"):
        verify_live_ticket(settings, ticket, "meeting-2")
    with pytest.raises(LiveTicketError, match="Invalid"):
        verify_live_ticket(settings, ticket + "x", "meeting-1")


def test_live_ticket_expires(monkeypatch):
    settings = Settings(_env_file=None, secret_key="ticket-secret", live_ticket_ttl_seconds=60)
    ticket, _ = create_live_ticket(settings, "meeting-1", "user-1")
    monkeypatch.setattr("app.services.live.time.time", lambda: 10**12)
    with pytest.raises(LiveTicketError, match="expired"):
        verify_live_ticket(settings, ticket, "meeting-1")


def test_live_ws_url_uses_websocket_scheme():
    settings = Settings(
        _env_file=None,
        public_base_url="https://api.example.com",
        secret_key="x",
    )
    assert live_ws_url(settings, "m1", "a+b/c=") == (
        "wss://api.example.com/meetings/m1/live?ticket=a%2Bb%2Fc%3D"
    )


def test_finalize_live_session_stores_audio_and_transcript(tmp_path):
    settings = Settings(
        _env_file=None,
        app_env="test",
        auth_mode="test",
        database_url=f"sqlite:///{tmp_path / 'live.db'}",
        data_dir=tmp_path,
        test_user_email="test@lowi.local",
        test_user_name="Test User",
    )
    configure_engine(settings.database_url)
    init_db(settings)

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "test@lowi.local"))
        assert user is not None
        meeting = Meeting(user_id=user.id, title="Live meeting")
        db.add(meeting)
        db.commit()
        db.refresh(meeting)
        live_session = LiveSession(
            meeting_id=meeting.id,
            user_id=user.id,
            source="mic",
            status="recording",
            started_at=datetime.now(UTC),
        )
        db.add(live_session)
        db.commit()
        db.refresh(live_session)
        meeting_id = meeting.id
        session_id = live_session.id

    pcm_path = tmp_path / "capture.pcm"
    pcm_path.write_bytes(b"\x00\x00" * 1600)
    storage = LocalStorage(tmp_path / "objects")
    queue = FakeQueue()

    asyncio.run(
        finalize_live_session(
            session_id=session_id,
            meeting_id=meeting_id,
            settings=settings,
            storage=storage,
            queue=queue,
            pcm_path=pcm_path,
            transcript_text="Hello live",
            segments=[{"sequence": 1, "text": "Hello live"}],
            duration_seconds=1.0,
            audio_bytes=3200,
        )
    )

    with SessionLocal() as db:
        meeting = db.get(Meeting, meeting_id)
        live_session = db.get(LiveSession, session_id)
        recording = db.scalar(select(Recording).where(Recording.meeting_id == meeting_id))
        transcript = db.scalar(select(Transcript).where(Transcript.meeting_id == meeting_id))

        assert meeting is not None and meeting.status == "transcribed"
        assert live_session is not None and live_session.status == "finalizing"
        assert recording is not None and recording.source == "live"
        assert transcript is not None and transcript.source == "live"
        assert transcript.raw_text == "Hello live"
        assert queue.jobs and queue.jobs[0]["kind"] == "pipeline"

        with (
            storage.materialize(recording.storage_key) as path,
            wave.open(str(path), "rb") as wav,
        ):
            assert wav.getframerate() == 16000
            assert wav.getnchannels() == 1
            assert wav.getnframes() == 1600

    assert not pcm_path.exists()


def test_live_websocket_streams_and_finalizes(client, settings):
    client.app.state.runtime.realtime = FakeRealtime()
    queue = FakeQueue()
    client.app.state.runtime.queue = queue

    created = client.post("/meetings", json={"title": "Live meeting"})
    meeting_id = created.json()["id"]

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == settings.test_user_email))
        assert user is not None
        user_id = user.id

    ticket, _ = create_live_ticket(settings, meeting_id, user_id)
    with client.websocket_connect(
        f"/meetings/{meeting_id}/live?ticket={ticket}&source=mic"
    ) as websocket:
        first = websocket.receive_json()
        assert first["type"] == "connecting"
        ready = websocket.receive_json()
        assert ready["type"] == "ready"

        websocket.send_bytes(b"\x00\x00" * 1600)
        websocket.send_json({"type": "stop"})

        types: list[str] = []
        for _ in range(30):
            message = websocket.receive_json()
            types.append(message["type"])
            if message["type"] in {"stopped", "error"}:
                break

    assert "stopped" in types
    assert queue.jobs and queue.jobs[0]["kind"] == "pipeline"

    with SessionLocal() as db:
        live_session = db.scalar(select(LiveSession).where(LiveSession.meeting_id == meeting_id))
        transcript = db.scalar(select(Transcript).where(Transcript.meeting_id == meeting_id))
        recording = db.scalar(select(Recording).where(Recording.meeting_id == meeting_id))
        assert live_session is not None and live_session.status == "finalizing"
        assert transcript is not None and transcript.raw_text == "Hello live"
        assert recording is not None and recording.source == "live"


def test_pipeline_completes_a_finalizing_live_session(tmp_path, monkeypatch):
    from app.db.models import Recording
    from app.services.pipeline import run_pipeline
    from app.services.storage import LocalStorage
    from app.services.transcription import TranscriptPayload

    settings = Settings(
        _env_file=None,
        app_env="test",
        auth_mode="test",
        database_url=f"sqlite:///{tmp_path / 'pipeline.db'}",
        data_dir=tmp_path,
        test_user_email="test@lowi.local",
        test_user_name="Test User",
        discord_webhook_url="",
    )
    configure_engine(settings.database_url)
    init_db(settings)

    storage = LocalStorage(tmp_path / "objects")
    storage.put("meetings/m/recordings/r.wav", io.BytesIO(b"audio"), "audio/wav")

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "test@lowi.local"))
        assert user is not None
        meeting = Meeting(user_id=user.id, title="Live pipeline")
        db.add(meeting)
        db.commit()
        db.refresh(meeting)
        live_session = LiveSession(
            meeting_id=meeting.id,
            user_id=user.id,
            source="mic",
            status="finalizing",
            started_at=datetime.now(UTC),
        )
        db.add(live_session)
        db.add(
            Recording(
                meeting_id=meeting.id,
                storage_backend="local",
                storage_key="meetings/m/recordings/r.wav",
                content_type="audio/wav",
                size_bytes=5,
                source="live",
                status="stored",
            )
        )
        db.commit()
        meeting_id = meeting.id
        session_id = live_session.id

    monkeypatch.setattr(
        "app.services.pipeline.transcribe_file",
        lambda settings, path: TranscriptPayload(
            raw_text="Batch transcript.", diarized_json={"text": "batch"}, language="en"
        ),
    )

    def complete(model, system, user):
        return {
            "decisions": [],
            "action_items": [],
            "open_questions": [],
            "key_points": [],
            "narrative": "Summary.",
        }

    run_pipeline(meeting_id, SessionLocal, settings, complete, storage)

    with SessionLocal() as db:
        meeting = db.get(Meeting, meeting_id)
        live_session = db.get(LiveSession, session_id)
        transcripts = db.scalars(
            select(Transcript).where(Transcript.meeting_id == meeting_id)
        ).all()
        assert meeting is not None and meeting.status == "summarized"
        assert live_session is not None and live_session.status == "completed"
        assert any(item.source == "live_batch" for item in transcripts)
