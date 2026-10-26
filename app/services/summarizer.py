"""Meeting summarization via AgentRouter models."""

import json
from datetime import UTC, date, datetime
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import ActionItem, Meeting, Summary, Transcript
from app.services.llm import CompleteJson

SUMMARY_SYSTEM = (
    "You write structured meeting notes from a transcript. "
    "Return JSON with keys: decisions (string list), "
    "action_items (list of objects with description, owner, due_date as YYYY-MM-DD or null), "
    "open_questions (string list), key_points (string list), narrative (string)."
)

CHUNK_SYSTEM = (
    "You extract structured notes from one part of a long meeting transcript. "
    "Return JSON with keys: decisions (string list), "
    "action_items (list of objects with description, owner, due_date as YYYY-MM-DD or null), "
    "open_questions (string list), key_points (string list), narrative (string). "
    "Keep names, numbers, and dates exact. Do not invent details."
)

SUMMARY_CHUNK_CHARS = 60_000


def summarize_transcript(
    settings: Settings,
    title: str,
    transcript: str,
    complete_json: CompleteJson,
) -> dict:
    if len(transcript) > SUMMARY_CHUNK_CHARS:
        data = _summarize_long_transcript(settings, title, transcript, complete_json)
    else:
        user = f"Meeting title: {title}\n\nTranscript:\n{transcript}"
        data = complete_json(settings.agentrouter_summary_model, SUMMARY_SYSTEM, user)
    _validate(data)
    return data


def _summarize_long_transcript(
    settings: Settings,
    title: str,
    transcript: str,
    complete_json: CompleteJson,
) -> dict:
    chunks = _split_chunks(transcript, SUMMARY_CHUNK_CHARS)
    parts: list[dict] = []
    for index, chunk in enumerate(chunks, start=1):
        user = (
            f"Meeting title: {title}\nPart {index} of {len(chunks)}.\n\n"
            f"Transcript part:\n{chunk}"
        )
        part = complete_json(settings.agentrouter_summary_model, CHUNK_SYSTEM, user)
        _validate(part)
        parts.append(part)

    context = json.dumps(parts, ensure_ascii=False)
    user = (
        f"Meeting title: {title}\n\n"
        f"These are notes from {len(parts)} consecutive parts of one meeting. "
        f"Merge them into one final summary. Remove duplicates. Keep every action item.\n\n"
        f"Part notes:\n{context}"
    )
    return complete_json(settings.agentrouter_summary_model, SUMMARY_SYSTEM, user)


def _split_chunks(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].lstrip()
    if remaining.strip():
        chunks.append(remaining.strip())
    return chunks or [text]


def _validate(data: dict) -> None:
    for key in ("decisions", "action_items", "open_questions", "key_points", "narrative"):
        if key not in data:
            raise ValueError(f"Summary is missing {key}")
    if not isinstance(data["narrative"], str):
        raise TypeError("Summary narrative must be a string")
    if not isinstance(data["action_items"], list):
        raise TypeError("Summary action_items must be a list")


def store_summary(db: Session, meeting: Meeting, structured: dict) -> Summary:
    summary = Summary(
        meeting_id=meeting.id,
        structured_json=structured,
        narrative=structured["narrative"],
    )
    db.add(summary)
    db.flush()

    existing = {
        (item.stable_key or _stable_key(item.description, item.owner)): item
        for item in db.scalars(
            select(ActionItem).where(ActionItem.meeting_id == meeting.id)
        ).all()
    }
    seen: set[str] = set()
    for raw in structured["action_items"]:
        if not isinstance(raw, dict):
            continue
        description = str(raw.get("description") or "").strip()
        if not description:
            continue
        owner = raw.get("owner")
        owner_text = str(owner) if owner else None
        stable_key = _stable_key(description, owner_text)
        seen.add(stable_key)
        parsed_due = _parse_due(raw.get("due_date"))
        item = existing.get(stable_key)
        if item is None:
            db.add(
                ActionItem(
                    meeting_id=meeting.id,
                    description=description,
                    owner=owner_text,
                    due_date=parsed_due,
                    status="open",
                    source_summary_id=summary.id,
                    stable_key=stable_key,
                )
            )
        else:
            item.description = description
            item.owner = owner_text
            item.due_date = parsed_due
            item.source_summary_id = summary.id
            item.updated_at = datetime.now(UTC)

    for stable_key, item in existing.items():
        if stable_key not in seen:
            db.delete(item)
    return summary


def _parse_due(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _stable_key(description: str, owner: str | None) -> str:
    raw = f"{description.strip().lower()}|{(owner or '').strip().lower()}"
    return sha256(raw.encode("utf-8")).hexdigest()[:32]


def latest_transcript(db: Session, meeting_id: str) -> Transcript | None:
    return db.scalar(
        select(Transcript)
        .where(Transcript.meeting_id == meeting_id)
        .order_by(Transcript.created_at.desc())
    )
