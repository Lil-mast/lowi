from datetime import date

from app.services.transcription import TranscriptPayload

SUMMARY = {
    "decisions": ["Ship the notes"],
    "action_items": [
        {"description": "Send the recap", "owner": "Ada", "due_date": "2026-10-01"}
    ],
    "open_questions": ["Who owns billing?"],
    "key_points": ["Launch date moved"],
    "narrative": "The team agreed to ship the notes.",
}


def fake_complete(model, system, user):
    if "brief" in system:
        return {"brief": "Review open items before the call."}
    return SUMMARY


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root_is_not_a_404(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Streamlit" in response.text
    assert "/docs" in response.text


def test_create_and_list_meetings(client):
    created = client.post("/meetings", json={"title": "Standup"})
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "scheduled"
    assert body["prep_brief"] is None
    listed = client.get("/meetings")
    assert listed.status_code == 200
    assert listed.json()[0]["title"] == "Standup"
    fetched = client.get(f"/meetings/{body['id']}")
    assert fetched.json()["id"] == body["id"]
    missing = client.get("/meetings/missing")
    assert missing.status_code == 404


def test_prep_brief(client):
    client.app.state.runtime.complete_json = fake_complete
    response = client.post("/meetings", json={"title": "Planning", "generate_prep": True})
    assert response.status_code == 200
    assert response.json()["prep_brief"] == "Review open items before the call."


def test_upload_pipeline_summary_pdf_and_actions(client, monkeypatch):
    client.app.state.runtime.complete_json = fake_complete

    def fake_transcribe(settings, path):
        assert path.read_bytes() == b"audio-bytes"
        return TranscriptPayload(raw_text="We should ship the notes.", diarized_json={"text": "ok"}, language="en")

    monkeypatch.setattr("app.services.pipeline.transcribe_file", fake_transcribe)
    created = client.post("/meetings", json={"title": "Review"})
    meeting_id = created.json()["id"]
    uploaded = client.post(
        f"/meetings/{meeting_id}/upload",
        files={"file": ("notes.mp3", b"audio-bytes", "audio/mpeg")},
    )
    assert uploaded.status_code == 200
    detail = client.get(f"/meetings/{meeting_id}").json()
    assert detail["status"] == "summarized"
    assert detail["transcript"]["raw_text"] == "We should ship the notes."
    assert detail["summary"]["narrative"].startswith("The team agreed")
    items = client.get("/action-items").json()
    assert items[0]["description"] == "Send the recap"
    assert items[0]["owner"] == "Ada"
    assert items[0]["due_date"] == date(2026, 10, 1).isoformat()
    pdf = client.get(f"/meetings/{meeting_id}/pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    transcript = client.get(f"/meetings/{meeting_id}/transcript")
    assert transcript.status_code == 200


def test_discord_send(client, monkeypatch):
    client.app.state.runtime.complete_json = fake_complete
    sent = {}

    def fake_send(webhook_url, meeting, summary):
        sent["url"] = webhook_url
        sent["title"] = meeting.title

    monkeypatch.setattr("app.api.routes.meetings.send_summary", fake_send)
    client.app.state.settings.discord_webhook_url = "https://discord.example/webhook"
    created = client.post("/meetings", json={"title": "Retro"})
    meeting_id = created.json()["id"]
    client.app.state.runtime.complete_json = fake_complete
    # Store a transcript directly through summarize after a fake upload path is unnecessary:
    from app.db.models import Transcript
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        db.add(Transcript(meeting_id=meeting_id, raw_text="Talked about retro.", diarized_json={}, language="en"))
        db.commit()
    summarized = client.post(f"/meetings/{meeting_id}/summarize")
    assert summarized.status_code == 200
    posted = client.post(f"/meetings/{meeting_id}/send-discord")
    assert posted.status_code == 200
    assert sent["title"] == "Retro"
    assert client.get(f"/meetings/{meeting_id}").json()["status"] == "sent"


def test_empty_upload(client):
    created = client.post("/meetings", json={"title": "Empty"})
    response = client.post(
        f"/meetings/{created.json()['id']}/upload",
        files={"file": ("notes.mp3", b"", "audio/mpeg")},
    )
    assert response.status_code == 400
