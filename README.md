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
             │ ElevenLabs │ │  LLM       │ │  Discord   │
             │ Scribe v2  │ │ (OpenAI /  │ │  Webhook   │
             │ (STT)      │ │  Claude /  │ │            │
             └────────────┘ │  Grok)     │ └────────────┘
                            └────────────┘
                                   │
                                   ▼
                            ┌────────────┐
                            │ Object     │
                            │ Storage    │
                            │ (R2 / S3)  │
                            │ audio +    │
                            │ PDFs       │
                            └────────────┘
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
   - Generate a clean PDF
   - Store transcript, summary, and PDF references in Neon
   - Optionally notify via email or other channels

### Recommended Tech Stack

| Layer              | Choice                          | Notes |
|--------------------|----------------------------------|-------|
| API                | **FastAPI**                      | Async, great DX, automatic OpenAPI |
| Database           | **Neon** (Postgres)              | Serverless Postgres, branching, good for AI apps |
| ORM / Migrations   | SQLAlchemy 2.0 + Alembic         | Or Prisma if preferred |
| Background jobs    | **ARQ** (Redis) or Celery        | Start with ARQ for simplicity |
| Transcription      | **ElevenLabs Scribe v2**         | Excellent accuracy + diarization + Python SDK |
| LLM                | Agent router   | Structured output via JSON mode or tool calling |
| Object storage     | Cloudflare R2 or AWS S3          | Cheap storage for audio + PDFs |
| PDF generation     | WeasyPrint or ReportLab          | Markdown → PDF is cleanest |
| Auth               | JWT (simple) or Clerk / Auth0    | Start simple |
| Calendar (optional)| Google Calendar API              | For automatic prep triggers |
| Frontend (optional)| Streamlit  | API-first design |
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
│   │   └── migrations/         # Alembic
│   ├── api/
│   │   ├── routes/
│   │   │   ├── meetings.py
│   │   │   ├── transcripts.py
│   │   │   └── health.py
│   │   └── deps.py
│   ├── services/
│   │   ├── transcription.py    # ElevenLabs client
│   │   ├── summarizer.py       # LLM summarization
│   │   ├── prep.py             # Meeting preparation brief
│   │   ├── discord.py          # Discord webhook
│   │   ├── pdf.py              # PDF generation
│   │   └── storage.py          # R2/S3 upload
│   ├── workers/
│   │   └── tasks.py            # Background jobs (ARQ)
│   └── schemas/                # Pydantic models
├── frontend/                   # Optional simple UI
├── scripts/
│   └── seed.py
├── tests/
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
- **recordings** – id, meeting_id, storage_key, duration_seconds, status
- **transcripts** – id, meeting_id, raw_text, diarized_json, language
- **summaries** – id, meeting_id, structured_json, narrative, pdf_storage_key
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
OPENAI_API_KEY=sk-...                # or ANTHROPIC_API_KEY / XAI_API_KEY
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=meeting-agent
R2_ENDPOINT=https://xxx.r2.cloudflarestorage.com
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

# 4. Migrations
uv run alembic upgrade head

# 5. Run API
uv run uvicorn app.main:app --reload

# 6. (Optional) Run worker
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

### Summarization Prompt (example)

Force structured JSON output with fields: `decisions`, `action_items`, `open_questions`, `key_points`, `narrative`.

### PDF

Convert the structured summary + transcript excerpt into Markdown, then render with WeasyPrint for nice typography.

### Discord

Simple webhook POST with embeds (title, action items as fields, link to PDF).

---

## Roadmap / Next Steps

- [x] Core upload → transcribe → summarize → Discord + PDF
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

Built for people who want meeting notes without the administrative drag.
```
