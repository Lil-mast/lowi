"""ElevenLabs Scribe transcription."""

from dataclasses import dataclass
from pathlib import Path

from elevenlabs.client import ElevenLabs

from app.config import Settings


@dataclass(frozen=True)
class TranscriptPayload:
    raw_text: str
    diarized_json: dict
    language: str | None


def _as_dict(result: object) -> dict:
    if hasattr(result, "model_dump"):
        data = result.model_dump()
    elif isinstance(result, dict):
        data = result
    else:
        data = {"text": getattr(result, "text", "")}
    return data if isinstance(data, dict) else {"text": str(result)}


def transcribe_file(settings: Settings, path: Path) -> TranscriptPayload:
    if not settings.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set")
    client = ElevenLabs(api_key=settings.elevenlabs_api_key)
    with path.open("rb") as audio_file:
        result = client.speech_to_text.convert(
            file=audio_file,
            model_id="scribe_v2",
            diarize=True,
            tag_audio_events=True,
        )
    data = _as_dict(result)
    language = data.get("language_code") or data.get("language")
    return TranscriptPayload(
        raw_text=str(data.get("text") or ""),
        diarized_json=data,
        language=str(language) if language else None,
    )
