# LoWi

A simple, production-oriented meeting intelligence agent built with **Python + FastAPI + Neon Postgres**.

It helps you:
1. **Prepare** for upcoming meetings (context + agenda + previous action items)
2. **Record / upload** meeting audio
3. **Transcribe** with high accuracy (ElevenLabs Scribe v2)
4. **Summarize** into structured notes (decisions, action items, open questions)
5. **Distribute** the summary to Discord
6. **Archive** a clean PDF for record-keeping

---

## Architecture Overview

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│  Client / UI    │────▶│  FastAPI Backend     │────▶│  Neon Postgres  │
│  (web / CLI)    │     │  (API + Workers)     │     │  (meetings,     │
└─────────────────┘     └──────────┬───────────┘     │   transcripts,  │
                                   │                 │   summaries)    │
                                   │                 └─────────────────┘
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
             ┌────────────┐ ┌────────────┐ ┌────────────┐
             │ ElevenLabs │ │ AgentRouter│ │  Discord   │
             │ Scribe v2  │ │ LLM models │ │  Webhook   │
             │ (STT)      │ │            │ │            │
             └────────────┘ └────────────┘ └────────────┘
```

### Core Flow

1. **Prep**  
   User (or calendar webhook) creates a meeting → system pulls previous related meetings + action items → LLM generates a short prep brief.

2. **Record / Upload**  
   - Option A (MVP): User uploads audio/video file after the meeting.  
   - Option B: Browser-based recording (MediaRecorder) or desktop capture.  
   - Option C (future): Meeting bot that joins Zoom/Meet/Teams.

3. **Transcribe**  
   Audio is sent to **ElevenLabs Speech-to-Text** (`scribe_v2` or `scribe_v2_realtime`).  
   We enable diarization so speakers are labeled.

4. **Summarize**  
   Transcript + meeting metadata → LLM produces a structured summary:
   - Key decisions
   - Action items (owner + due date)
   - Open questions
   - Notable discussion points
   - Short narrative summary

5. **Distribute & Archive**
   - Post formatted summary to Discord (webhook or bot)
   - Render a PDF on download (no blob store yet)
   - Store transcript and summary JSON in Neon
   - Optionally notify via email or other channels later

### Recommended Tech Stack

| Layer              | Choice                          | Notes |
|--------------------|----------------------------------|-------|
| API                | **FastAPI**                      | Async, great DX, automatic OpenAPI |
| Database           | **Neon** (Postgres)              | Serverless Postgres, branching, good for AI apps |
| ORM / schema       | SQLAlchemy 2.0 + `create_all`    | No Alembic yet — see below |
| Background jobs    | **ARQ** (Redis) or Celery        | Start with ARQ for simplicity |
| Transcription      | **ElevenLabs Scribe v2**         | Excellent accuracy + diarization + Python SDK |
| LLM                | **AgentRouter**                  | Token models: `claude-opus-4-8`, `deepseek-v4-flash` |
| Object storage     | Deferred                         | Local `data/` if needed; R2/S3 later |
| PDF generation     | WeasyPrint                       | Generate on download, do not archive blobs yet |
| Auth               | JWT (simple) or Clerk / Auth0    | Start simple |
| Calendar (optional)| Google Calendar / Zapier later   | After core pipeline |
| Frontend           | **Streamlit**                    | Thin UI over the FastAPI API |
| Discord            | Webhook (easiest) or discord.py  | Webhook is enough for summaries |

**Why ElevenLabs for transcription?**  
As of 2026, ElevenLabs Scribe v2 offers industry-leading accuracy, strong diarization (up to 32 speakers), word-level timestamps, multi-language support, and a clean Python SDK. It also has a realtime variant if you later want live captions. Perfect fit for this use case.

---

## Project Structure

```
lowi/
├── app/
│   ├── main.py                 # FastAPI entrypoint
│   ├── config.py               # Settings (pydantic-settings)
│   ├── db/
│   │   ├── session.py
│   │   ├── models.py           # SQLAlchemy models
│   │   └── migrations/         # Optional SQL later; unused for now
│   ├── api/
│   │   ├── routes/
│   │   │   ├── meetings.py
│   │   │   ├── transcripts.py
│   │   │   └── health.py
│   │   └── deps.py
│   ├── services/
│   │   ├── transcription.py    # ElevenLabs client
│   │   ├── summarizer.py       # AgentRouter summarization
│   │   ├── prep.py             # Meeting preparation brief
│   │   ├── discord.py          # Discord webhook
│   │   ├── pdf.py              # PDF generation
│   │   └── storage.py          # Local files for now (R2 deferred)
│   ├── workers/
│   │   └── tasks.py            # Background jobs (ARQ)
│   └── schemas/                # Pydantic models
├── frontend/
│   └── app.py                  # Streamlit UI (calls FastAPI)
├── scripts/
│   └── seed.py
├── tests/
├── docs/
│   └── zapier.md               # Deferred Zapier MCP integrations
├── .env.example
├── pyproject.toml
├── uv.lock
└── README.md
```

---

## Database Schema (Neon / Postgres)

Key tables:

- **users** – id, email, name, discord_webhook_url, settings
- **meetings** – id, user_id, title, scheduled_at, status, calendar_event_id, prep_brief
- **recordings** – id, meeting_id, local_path (optional), duration_seconds, status
- **transcripts** – id, meeting_id, raw_text, diarized_json, language
- **summaries** – id, meeting_id, structured_json, narrative
- **action_items** – id, meeting_id, description, owner, due_date, status

Use JSONB columns liberally for the structured summary and diarized transcript so you stay flexible.

---

## Key API Endpoints (sketch)

```
POST   /meetings                     # Create meeting + optional prep
GET    /meetings/{id}                # Get meeting + prep + summary
POST   /meetings/{id}/upload         # Upload audio → triggers transcription pipeline
POST   /meetings/{id}/summarize      # Force re-summarize
GET    /meetings/{id}/pdf            # Download PDF
POST   /meetings/{id}/send-discord   # Manually push to Discord
GET    /action-items                 # List open action items across meetings
```

The heavy lifting (transcription → summarize → PDF → Discord) runs as a background job after upload.

---

## Environment Variables

```bash
# .env.example
DATABASE_URL=postgresql://...@ep-xxx.us-east-2.aws.neon.tech/neondb
ELEVENLABS_API_KEY=sk_...
AGENTROUTER_API_KEY=sk_...
AGENTROUTER_BASE_URL=https://agentrouter.org/v1
AGENTROUTER_SUMMARY_MODEL=claude-opus-4-8
AGENTROUTER_PREP_MODEL=deepseek-v4-flash
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
REDIS_URL=redis://localhost:6379
SECRET_KEY=change-me
```

---

## Getting Started (Local)

```bash
# 1. Clone & install (uv creates .venv and installs from pyproject.toml)
uv sync

# 2. Set up Neon
# Create a project at https://neon.tech → copy connection string

# 3. Configure
cp .env.example .env
# fill in keys

# 4. Schema (dev): SQLAlchemy create_all — no Alembic yet

# 5. Run API (open /docs — the bare host used to 404)
uv run uvicorn app.main:app --reload
# http://127.0.0.1:8000/          index
# http://127.0.0.1:8000/docs      interactive API

# 6. Streamlit UI (talks to the API)
uv sync --group frontend
uv run streamlit run frontend/app.py

# 7. (Optional) Run worker
uv run arq app.workers.tasks.WorkerSettings
```

---

## Pipeline Implementation Notes

### Transcription (ElevenLabs)

```python
from elevenlabs.client import ElevenLabs

client = ElevenLabs(api_key=settings.ELEVENLABS_API_KEY)

transcription = client.speech_to_text.convert(
    file=audio_file,
    model_id="scribe_v2",
    diarize=True,
    tag_audio_events=True,
    language_code="eng",  # or None for auto-detect
)
```

### Summarization (AgentRouter)

All LLM calls go through **[AgentRouter](https://agentrouter.org/)** (`https://agentrouter.org/v1`), not vendor SDKs. It is OpenAI-compatible (`/v1/chat/completions`). Get a key at [the token console](https://agentrouter.org/console/token).

```python
from openai import OpenAI

client = OpenAI(
    api_key=settings.AGENTROUTER_API_KEY,
    base_url=settings.AGENTROUTER_BASE_URL,  # https://agentrouter.org/v1
)

completion = client.chat.completions.create(
    model=settings.AGENTROUTER_SUMMARY_MODEL,
    response_format={"type": "json_object"},
    messages=[...],
)
```

This token can call `claude-opus-4-8`, `claude-opus-5`, `deepseek-v4-flash`, and `gpt-6-astra`. We use **`claude-opus-4-8` for summaries** and **`deepseek-v4-flash` for prep**. Do not use `gpt-6-astra` or `claude-opus-5`. AgentRouter tops up quota twice daily (10:00 and 19:00 Beijing / 02:00 and 11:00 UTC). Cursor is a supported client.

Use `AGENTROUTER_SUMMARY_MODEL` for structured notes and `AGENTROUTER_PREP_MODEL` for shorter prep briefs. Force JSON with fields: `decisions`, `action_items`, `open_questions`, `key_points`, `narrative`.

### Schema (no Alembic for now)

Alembic is the usual SQLAlchemy companion, but it is extra ceremony while the tables are still changing. For v1 we create tables from models (`create_all`). Alternatives if we outgrow that:

| Tool | Fit |
|---|---|
| **SQLAlchemy `create_all`** | Fastest for early Neon; no migration history |
| **Plain `.sql` files** | Explicit, easy to review; we apply them ourselves |
| **Atlas** | Desired-state schema, good later if we want migrations without Alembic |
| **Alembic** | Add when production data must migrate in place |
| **Prisma** | Different ORM; do not mix with SQLAlchemy |

### Object storage (deferred)

Audio and PDFs do not need R2/S3 yet. Transcribe, keep text + JSON in Neon, and **render the PDF when someone downloads it**. Optional temp files go under `data/` (gitignored). Add Cloudflare R2 when we must keep original audio or serve PDFs as stable URLs.

### Streamlit

The backend stays API-first. Streamlit is a Python UI that calls FastAPI (create meeting, upload audio, show prep/summary, trigger Discord). It is faster to ship than a React app and matches this stack. It is not a replacement for the API: no business logic in `frontend/app.py`.

### PDF

Convert the structured summary + transcript excerpt into Markdown, then render with WeasyPrint when `/meetings/{id}/pdf` is requested.

### Discord

Simple webhook POST with embeds (title, action items as fields, link to PDF).

---

## Roadmap / Next Steps

- [x] Core upload → transcribe → summarize → Discord + PDF
- [ ] Streamlit UI over the API
- [ ] Object storage (R2/S3) when we need to keep audio or stable PDF URLs
- [ ] Zapier MCP integrations (Calendar, Gmail, extra Discord) — see [docs/zapier.md](docs/zapier.md)
- [ ] Calendar-triggered prep (Google Calendar)
- [ ] Browser-based live recording
- [ ] Real-time captions via Scribe v2 Realtime
- [ ] Action-item tracking & reminders
- [ ] Multi-user / team workspaces
- [ ] Meeting bot integrations (Zoom, Meet, Teams)
- [ ] Search across all past transcripts

---

## Design Principles

- **API-first** – everything useful is available via HTTP so you can later add a mobile app, Slack bot, or CLI.
- **Human-in-the-loop optional** – summaries can be reviewed/edited before Discord/PDF are finalized.
- **Cheap & simple first** – start with background tasks + Neon + R2. Add complexity only when needed.
- **Privacy-aware** – audio can be deleted after transcription if desired; store only what you need.

---

Feature notes: [docs/features.md](docs/features.md).

Built for people who want meeting notes without the administrative drag.
```
