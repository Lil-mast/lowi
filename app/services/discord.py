"""Discord webhook delivery."""

import httpx

from app.db.models import Meeting, Summary


def send_summary(webhook_url: str, meeting: Meeting, summary: Summary) -> None:
    if not webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not set")
    items = (summary.structured_json or {}).get("action_items") or []
    lines: list[str] = []
    for item in items[:10]:
        if isinstance(item, dict):
            lines.append(f"• {item.get('description', '')}")
        else:
            lines.append(f"• {item}")
    action_text = "\n".join(lines) or "None"
    payload = {
        "embeds": [
            {
                "title": meeting.title[:256],
                "description": (summary.narrative or "")[:4000],
                "fields": [{"name": "Action items", "value": action_text[:1024]}],
            }
        ]
    }
    response = httpx.post(webhook_url, json=payload, timeout=20)
    response.raise_for_status()
