from app.config import Settings, normalize_database_url
from app.services.calendar import event_to_item
from app.services.prep import generate_prep
from app.services.summarizer import SUMMARY_CHUNK_CHARS, summarize_transcript


def test_normalize_postgres_url():
    assert normalize_database_url("postgresql://db/app").startswith("postgresql+psycopg://")
    assert normalize_database_url("sqlite://").startswith("sqlite")


def test_event_to_item_uses_description_as_agenda():
    item = event_to_item(
        {
            "id": "evt",
            "summary": "Launch",
            "description": "Decide the date",
            "start": {"dateTime": "2026-09-24T15:00:00Z"},
            "htmlLink": "https://calendar.google.com/event",
        }
    )
    assert item["title"] == "Launch"
    assert item["agenda"] == "Decide the date"
    assert item["start"] == "2026-09-24T15:00:00Z"


def test_generate_prep_requires_brief():
    settings = Settings()

    def complete(model, system, user):
        return {"brief": "  Bring the deck.  "}

    assert generate_prep(settings, "context", complete) == "Bring the deck."


def test_summarize_rejects_incomplete_payload():
    settings = Settings()

    def complete(model, system, user):
        return {"narrative": "nope"}

    try:
        summarize_transcript(settings, "Title", "transcript", complete)
    except ValueError as exc:
        assert "decisions" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_summarize_chunks_a_long_transcript():
    settings = Settings(_env_file=None)
    calls: list[str] = []

    summary = {
        "decisions": ["Ship"],
        "action_items": [],
        "open_questions": [],
        "key_points": ["Launch"],
        "narrative": "Merged notes.",
    }

    def complete(model, system, user):
        calls.append(system)
        return summary

    transcript = ("word " * (SUMMARY_CHUNK_CHARS // 5 + 100)).strip()
    result = summarize_transcript(settings, "Long meeting", transcript, complete)
    assert result["narrative"] == "Merged notes."
    assert len(calls) >= 3
    assert "one part" in calls[0]
