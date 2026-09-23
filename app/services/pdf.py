"""On-demand PDF rendering from a stored summary."""

import html

from weasyprint import HTML

from app.db.models import Meeting, Summary


def render_summary_pdf(meeting: Meeting, summary: Summary) -> bytes:
    structured = summary.structured_json or {}
    sections = [
        ("Decisions", structured.get("decisions") or []),
        ("Key points", structured.get("key_points") or []),
        ("Open questions", structured.get("open_questions") or []),
    ]
    body = [
        f"<h1>{html.escape(meeting.title)}</h1>",
        f"<p>{html.escape(summary.narrative)}</p>",
    ]
    items = structured.get("action_items") or []
    if items:
        body.append("<h2>Action items</h2><ul>")
        for item in items:
            if isinstance(item, dict):
                text = str(item.get("description") or "")
                owner = item.get("owner")
                if owner:
                    text = f"{text} — {owner}"
            else:
                text = str(item)
            body.append(f"<li>{html.escape(text)}</li>")
        body.append("</ul>")
    for heading, values in sections:
        if not values:
            continue
        body.append(f"<h2>{html.escape(heading)}</h2><ul>")
        for value in values:
            body.append(f"<li>{html.escape(str(value))}</li>")
        body.append("</ul>")
    document = (
        "<html><body style='font-family: sans-serif; margin: 2rem;'>"
        + "".join(body)
        + "</body></html>"
    )
    return HTML(string=document).write_pdf()
