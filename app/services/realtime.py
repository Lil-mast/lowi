"""ElevenLabs Scribe Realtime WebSocket client."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol
from urllib.parse import urlencode

import websockets
from websockets.exceptions import WebSocketException

from app.config import Settings

REALTIME_URL = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"


class RealtimeError(Exception):
    """The realtime provider could not be reached or rejected the session."""


class RealtimeClient(Protocol):
    def connect(self) -> Any: ...


class ElevenLabsRealtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[Any]:
        if not self.settings.elevenlabs_api_key:
            raise RealtimeError("ELEVENLABS_API_KEY is not configured")

        query = urlencode(
            {
                "model_id": self.settings.elevenlabs_realtime_model,
                "audio_format": "pcm_16000",
                "commit_strategy": self.settings.live_commit_strategy,
                "vad_silence_threshold_secs": self.settings.live_vad_silence_secs,
                "include_timestamps": "false",
                "include_language_detection": "false",
                "keepalive_interval_ms": 5000,
            }
        )
        uri = f"{REALTIME_URL}?{query}"
        try:
            socket = await websockets.connect(
                uri,
                additional_headers={"xi-api-key": self.settings.elevenlabs_api_key},
                max_size=4 * 1024 * 1024,
                open_timeout=15,
                ping_interval=20,
                ping_timeout=20,
            )
        except (OSError, WebSocketException) as exc:
            raise RealtimeError("Could not connect to the realtime transcription service") from exc
        try:
            yield socket
        finally:
            await socket.close()


def build_realtime(settings: Settings) -> RealtimeClient:
    return ElevenLabsRealtime(settings)
