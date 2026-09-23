---
name: lowi
description: How LoWi is built. Use when changing meetings, prep, transcription, summaries, PDF, Discord, the pipeline, or the Streamlit UI.
---

# LoWi

API-first meeting notes. FastAPI owns the work. Streamlit only calls HTTP.

Read [docs/features.md](../../../docs/features.md) before editing a feature.

## Rules

- Do not add Alembic, R2/S3, JWT, or Zapier calls inside the app.
- LLM calls go through AgentRouter (`app/services/llm.py`). Summary model is `claude-opus-4-8`. Prep model is `deepseek-v4-flash`. Do not use `gpt-6-astra` or `claude-opus-5`.
- Postgres URLs are rewritten to `postgresql+psycopg://` in `normalize_database_url`.
- Tests use in-memory SQLite via `create_app(Settings(...))`. Do not require Neon.
- External clients are injected through `app.state.runtime.complete_json` and by patching `transcribe_file` / `send_summary`. Keep that so tests stay offline.
- `GET /` must stay a 200. The API root is not the UI.

## Where each feature lives

| Feature | Code | HTTP |
|---|---|---|
| Health and index | `app/api/routes/health.py` | `GET /`, `GET /health` |
| Meetings | `app/api/routes/meetings.py` | `POST/GET /meetings`, `GET /meetings/{id}` |
| Prep | `app/services/prep.py` | `generate_prep` on create |
| Audio | `app/services/storage.py` | `POST /meetings/{id}/upload` |
| Transcription | `app/services/transcription.py` | `GET /meetings/{id}/transcript` |
| Summary | `app/services/summarizer.py` | `POST /meetings/{id}/summarize`, `GET /action-items` |
| PDF | `app/services/pdf.py` | `GET /meetings/{id}/pdf` |
| Discord | `app/services/discord.py` | `POST /meetings/{id}/send-discord` |
| Pipeline | `app/services/pipeline.py` | background task after upload |
| UI | `frontend/app.py` | Streamlit, no business logic |

## Streamlit

Follow `.agents/skills/developing-with-streamlit`. Sentence case, Material icons, `st.form` for create, sidebar for the meeting picker only, bordered containers for sections. Theme lives in `frontend/.streamlit/config.toml`.
