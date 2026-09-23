"""Meeting summarization via AgentRouter models."""

from datetime import date

from sqlalchemy import delete, select
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


def summarize_transcript(
    settings: Settings,
    title: str,
    transcript: str,
    complete_json: CompleteJson,
) -> dict:
    user = f"Meeting title: {title}\n\nTranscript:\n{transcript}"
    data = complete_json(settings.agentrouter_summary_model, SUMMARY_SYSTEM, user)
    for key in ("decisions", "action_items", "open_questions", "key_points", "narrative"):
        if key not in data:
            raise ValueError(f"Summary is missing {key}")
    if not isinstance(data["narrative"], str):
        raise TypeError("Summary narrative must be a string")
    if not isinstance(data["action_items"], list):
        raise TypeError("Summary action_items must be a list")
    return data


def store_summary(db: Session, meeting: Meeting, structured: dict) -> Summary:
    db.execute(delete(ActionItem).where(ActionItem.meeting_id == meeting.id))
    summary = Summary(
        meeting_id=meeting.id,
        structured_json=structured,
        narrative=structured["narrative"],
    )
    db.add(summary)
    for raw in structured["action_items"]:
        if not isinstance(raw, dict):
            continue
        description = str(raw.get("description") or "").strip()
        if not description:
            continue
        due = raw.get("due_date")
        parsed_due = None
        if due:
            parsed_due = date.fromisoformat(str(due)[:10])
        owner = raw.get("owner")
        db.add(
            ActionItem(
                meeting_id=meeting.id,
                description=description,
                owner=str(owner) if owner else None,
                due_date=parsed_due,
                status="open",
            )
        )
    return summary


def latest_transcript(db: Session, meeting_id: str) -> Transcript | None:
    return db.scalar(
        select(Transcript)
        .where(Transcript.meeting_id == meeting_id)
        .order_by(Transcript.created_at.desc())
    )
