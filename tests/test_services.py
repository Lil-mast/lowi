from app.config import Settings, normalize_database_url
from app.services.prep import generate_prep
from app.services.summarizer import summarize_transcript


def test_normalize_postgres_url():
    assert normalize_database_url("postgresql://db/app").startswith("postgresql+psycopg://")
    assert normalize_database_url("sqlite://").startswith("sqlite")


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
