"""Meeting preparation brief via AgentRouter models."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import ActionItem, Meeting, Summary
from app.services.llm import CompleteJson

PREP_SYSTEM = (
    "You prepare a short briefing before a meeting. "
    'Return JSON with one string field: "brief". '
    "Use prior meetings and open action items. Be concrete and under 200 words."
)


def build_prep_context(db: Session, user_id: str, title: str) -> str:
    meetings = db.scalars(
        select(Meeting)
        .where(Meeting.user_id == user_id)
        .order_by(Meeting.created_at.desc())
        .limit(8)
    ).all()
    lines = [f"Upcoming meeting: {title}"]
    for meeting in meetings:
        summary = db.scalar(
            select(Summary)
            .where(Summary.meeting_id == meeting.id)
            .order_by(Summary.created_at.desc())
        )
        if summary is None and not meeting.prep_brief:
            continue
        lines.append(f"\nPrevious: {meeting.title} ({meeting.status})")
        if summary is not None:
            lines.append(summary.narrative)
    items = db.scalars(
        select(ActionItem)
        .join(Meeting)
        .where(Meeting.user_id == user_id, ActionItem.status == "open")
        .order_by(ActionItem.created_at.desc())
        .limit(20)
    ).all()
    if items:
        lines.append("\nOpen action items:")
        for item in items:
            owner = f" ({item.owner})" if item.owner else ""
            lines.append(f"- {item.description}{owner}")
    return "\n".join(lines)


def generate_prep(
    settings: Settings,
    context: str,
    complete_json: CompleteJson,
) -> str:
    data = complete_json(settings.agentrouter_prep_model, PREP_SYSTEM, context)
    brief = data.get("brief")
    if not isinstance(brief, str) or not brief.strip():
        raise ValueError("Prep model did not return a brief")
    return brief.strip()
