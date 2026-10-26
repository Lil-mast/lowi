# LoWi

A production-oriented meeting intelligence app built with **Python + FastAPI + Neon Postgres**.

It helps you:
1. **Prepare** for upcoming meetings (context + agenda + previous action items)
2. **Record live** from the browser microphone or a shared meeting tab, or **upload** an existing recording
3. **Transcribe** live captions with ElevenLabs Scribe Realtime, then run batch Scribe with diarization
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
   - **Live:** the Streamlit browser component streams 16 kHz PCM to a FastAPI WebSocket, which proxies it to ElevenLabs Scribe Realtime. The mic or a shared meeting tab works. No bot joins Zoom/Meet/Teams.
   - **Upload:** an audio/video file is stored through the storage abstraction and queued for batch transcription.

3. **Transcribe**
   Live captions arrive while the meeting runs. On stop, the captured PCM is converted to WAV and batch-transcribed with **ElevenLabs Scribe v2** and diarization, so the final transcript has speaker labels. Uploads go straight to batch transcription.

4. **Summarize**
   Transcript + meeting metadata → LLM produces a structured summary:
   - Key decisions
   - Action items (owner + due date)
   - Open questions
   - Notable discussion points
   - Short narrative summary
   Long transcripts are chunk-summarized before the final merge.

5. **Distribute & Archive**
   - Post formatted summary to Discord (webhook or bot)
   - Render a PDF on download (no stored PDF blob)
   - Store transcript, summary, and audio object metadata in Neon
   - Optionally notify via email or other channels later

### Recommended Tech Stack

| Layer              | Choice                          | Notes |
|--------------------|----------------------------------|-------|
| API                | **FastAPI**                      | Async, great DX, automatic OpenAPI |
| Database           | **Neon** (Postgres)              | Serverless Postgres, branching, good for AI apps |
| ORM / schema       | SQLAlchemy 2.0 + plain SQL migrations | Custom runner, checksums, advisory lock; no Alembic |
| Background jobs    | **ARQ** (Redis) or inline      | ARQ in production; inline in dev/tests |
| Transcription      | **ElevenLabs Scribe v2**         | Realtime captions + batch diarization |
| LLM                | **AgentRouter**                  | Token models: `claude-opus-4-8`, `deepseek-v4-flash` |
| Object storage     | Local disk or S3-compatible     | Local in dev; S3/R2/Neon Object Storage in production |
| PDF generation     | WeasyPrint                       | Generate on download, do not archive blobs |
| Auth               | Neon Auth (Managed Better Auth) | REST + JWKS, then opaque LoWi sessions |
| Calendar (optional)| Google Calendar                  | Read-only events + callback |
| Frontend           | **Streamlit**                    | Thin UI over the FastAPI API |
| Discord            | Webhook (easiest) or discord.py  | Webhook is enough for summaries |

**Why ElevenLabs for transcription?**
As of 2026, ElevenLabs Scribe v2 offers industry-leading accuracy, strong diarization (up to 32 speakers), word-level timestamps, and multi-language support. Scribe Realtime drives live captions during a meeting; the batch model adds speaker labels at finalize. Perfect fit for this use case.

---

## Project Structure

```
lowi/
├── app/
│   ├── main.py                 # FastAPI entrypoint
│   ├── config.py               # Settings + production validation
│   ├── db/
│   │   ├── session.py
│   │   ├── models.py           # SQLAlchemy models
│   │   ├── migrate.py          # Plain SQL migration runner
│   │   └── migrations/         # 0001–0005
│   ├── api/
│   │   ├── routes/
│   │   │   ├── auth.py
│   │   │   ├── meetings.py
│   │   │   ├── transcripts.py
│   │   │   ├── live.py
│   │   │   ├── calendar.py
│   │   │   └── health.py
│   │   └── deps.py
│   ├── services/
│   │   ├── auth.py             # Neon Auth REST + JWKS
│   │   ├── sessions.py         # Opaque LoWi sessions
│   │   ├── users.py
│   │   ├── transcription.py    # Batch ElevenLabs client
│   │   ├── realtime.py         # Scribe Realtime WebSocket client
│   │   ├── live.py             # Tickets, finalize, live transcript
│   │   ├── summarizer.py       # AgentRouter summarization
│   │   ├── prep.py             # Meeting preparation brief
│   │   ├── pipeline.py         # Transcribe → summarize → Discord
│   │   ├── jobs.py             # Inline / ARQ queue
│   │   ├── storage.py          # Local / S3-compatible storage
│   │   ├── discord.py
│   │   └── pdf.py
│   ├── workers/
│   │   └── tasks.py            # ARQ WorkerSettings
│   └── schemas/
├── frontend/
│   ├── app.py                  # Streamlit UI
│   └── live.py                 # CCv2 live-capture component
├── scripts/
│   ├── seed.py
│   └── claim_legacy_data.py
├── tests/
├── docs/
├── .streamlit/
│   └── config.toml             # Theme
├── .env.example
├── pyproject.toml
├── uv.lock
└── README.md
```

---

## Database Schema (Neon / Postgres)

Key tables:

- **users** – id, email, name, `neon_auth_user_id`, discord_webhook_url, settings
- **sessions** – SHA-256 token hash, expiry, user agent, IP
- **meetings** – id, user_id, title, scheduled_at, status, prep_brief, error fields, pipeline_version
- **recordings** – id, meeting_id, storage backend/key, checksum, source, duration, status
- **transcripts** – id, meeting_id, raw_text, diarized_json, language, source (`upload` / `live_batch`)
- **summaries** – id, meeting_id, structured_json, narrative, model, chunk_count
- **action_items** – id, meeting_id, description, owner, due_date, status, stable_key
- **live_sessions** – id, meeting_id, user_id, status, source, duration, audio_bytes, error
- **live_segments** – committed realtime captions for a live session
- **pipeline_runs** – one attempt per background stage with timing and error fields

Transcript and summary payloads are JSON so the schema can evolve without a migration. Schema changes go through the SQL files, not `create_all`.

---

## Key API Endpoints (sketch)

```
POST   /auth/register                 # Neon Auth sign-up → local opaque session
POST   /auth/login                    # Neon Auth sign-in → local opaque session
GET    /auth/me                       # Current user
GET    /auth/config                   # Public: whether login is required
POST   /meetings                      # Create meeting + optional prep
GET    /meetings/{id}                 # Get meeting + prep + summary
POST   /meetings/{id}/upload          # Upload audio → queue transcription pipeline
POST   /meetings/{id}/live/ticket     # Short-lived WebSocket ticket
WS     /meetings/{id}/live            # Browser PCM → ElevenLabs Scribe Realtime
POST   /meetings/{id}/summarize       # Force re-summarize
GET    /meetings/{id}/transcript      # Latest transcript
GET    /meetings/{id}/pdf             # Download PDF
POST   /meetings/{id}/send-discord    # Manually push to Discord
GET    /action-items                  # Open action items across meetings
```

Auth endpoints are public; every meeting and action-item route requires `Authorization: Bearer <LoWi session token>`. The heavy lifting (batch transcription → summarize → Discord) runs as a queued job after upload or live finalize.

---

## Environment Variables

```bash
# .env.example
APP_ENV=development
DATABASE_URL=postgresql://...@ep-xxx.us-east-2.aws.neon.tech/neondb
SECRET_KEY=change-me
PUBLIC_BASE_URL=http://127.0.0.1:8000
UI_BASE_URL=http://127.0.0.1:8501

AUTH_MODE=dev                         # dev | neon
NEON_AUTH_BASE_URL=
NEON_AUTH_JWKS_URL=
NEON_AUTH_ISSUER=                     # optional; defaults to auth host origin
NEON_AUTH_AUDIENCE=                   # optional; defaults to auth host origin

ELEVENLABS_API_KEY=sk_...
AGENTROUTER_API_KEY=sk_...
AGENTROUTER_BASE_URL=https://agentrouter.org/v1
AGENTROUTER_SUMMARY_MODEL=claude-opus-4-8
AGENTROUTER_PREP_MODEL=deepseek-v4-flash
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

JOB_BACKEND=inline                    # inline | arq
REDIS_URL=redis://localhost:6379
STORAGE_BACKEND=local                 # local | s3
S3_BUCKET=
S3_REGION=us-east-1                     # R2: auto
```

Production validation requires `AUTH_MODE=neon`, `JOB_BACKEND=arq`, `STORAGE_BACKEND=s3`, an `https://` `PUBLIC_BASE_URL`, an `https://` `UI_BASE_URL`, a `SECRET_KEY` of at least 32 characters, and the Neon Auth URLs. See [SETUP.md](SETUP.md) for the full table.

---

## Getting Started (Local)

Full steps, env vars, and URLs: [SETUP.md](SETUP.md).

```bash
# 1. Clone & install (uv creates .venv and installs from pyproject.toml)
uv sync --group frontend --group dev

# 2. Set up Neon
# Create a project at https://neon.tech → copy connection string

# 3. Configure
cp .env.example .env
# fill in keys; AUTH_MODE=dev works without Neon Auth

# 4. Schema: pending SQL migrations run automatically at API startup
# (plain .sql files in app/db/migrations; no create_all, no Alembic)

# 5. Run API (open /docs — the bare host used to 404)
uv run uvicorn app.main:app --reload
# http://127.0.0.1:8000/          index
# http://127.0.0.1:8000/docs      interactive API

# 6. Streamlit UI (talks to the API)
uv run streamlit run frontend/app.py

# 7. (Optional) Run the ARQ worker instead of inline jobs
JOB_BACKEND=arq uv run arq app.workers.tasks.WorkerSettings
```

Render: Redis plus API, worker, and UI services in [render.yaml](render.yaml). See [SETUP.md](SETUP.md). Use Neon for `DATABASE_URL` and an S3-compatible bucket for audio.

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

### Live capture (Scribe Realtime)

The browser downsamples mic or tab audio to mono PCM16 at 16 kHz and sends binary frames over `WS /meetings/{id}/live?ticket=...`. The API wraps each frame in the JSON `input_audio_chunk` message ElevenLabs expects, so the API key never reaches the browser. Tickets are HMAC-signed, scoped to meeting + user, and expire after 15 minutes by default.

Realtime captions are not diarized. On stop, the API finalizes the PCM to WAV, stores it through the storage abstraction, writes a temporary live transcript, and queues the batch pipeline. Batch Scribe replaces the live transcript with speaker labels and the summary follows.

### Schema (plain SQL, no Alembic)

Schema changes live in `app/db/migrations/*.sql` and run through `app/db/migrate.py`. The runner records applied versions in `schema_migrations`, checks each file's SHA-256, and takes a Postgres advisory lock. It never edits applied migrations and never calls `create_all`.

| Tool | Fit |
|---|---|
| **Plain `.sql` + custom runner** | **Current.** Explicit, reviewable, works on Neon |
| SQLAlchemy `create_all` | Removed; no migration history |
| Atlas | Desired-state schema, optional later |
| Alembic | Not used by choice |
| Prisma | Different ORM; do not mix with SQLAlchemy |

### Object storage

Audio goes through `app/services/storage.py`. Development and tests use local disk under `data/`; production uses any S3-compatible bucket (Neon Object Storage, Cloudflare R2, AWS S3). Uploads are size-limited, SHA-256 hashed, and exposed as short-lived presigned URLs when needed. PDFs are still rendered on download and not stored.

### Streamlit

The backend stays API-first. Streamlit is a Python UI that calls FastAPI (login, live capture, upload, prep/summary, Discord). It is faster to ship than a React app and matches this stack. It is not a replacement for the API: no business logic in `frontend/app.py`. Live audio uses a Custom Components v2 widget in `frontend/live.py`.

### PDF

Convert the structured summary + transcript excerpt into Markdown, then render with WeasyPrint when `/meetings/{id}/pdf` is requested.

### Discord

Simple webhook POST with embeds (title, action items as fields, link to PDF).

---

## Roadmap / Next Steps

- [x] Core upload → transcribe → summarize → Discord + PDF
- [x] Streamlit UI over the API
- [x] Neon Auth + per-user data isolation
- [x] Plain SQL migrations and production fail-fast validation
- [x] Object storage (local + S3-compatible)
- [x] Browser live recording and realtime captions
- [x] Batch diarization after live capture
- [x] Action-item reconciliation and reminders data model
- [ ] Google OAuth login and Calendar-triggered prep
- [ ] Zapier MCP integrations (Calendar, Gmail, extra Discord) — see [docs/zapier.md](docs/zapier.md)
- [ ] Meeting bot integrations (Zoom, Meet, Teams)
- [ ] Search across all past transcripts
- [ ] Multi-user / team workspaces

---

## Design Principles

- **API-first** – everything useful is available via HTTP so you can later add a mobile app, Slack bot, or CLI.
- **Human-in-the-loop optional** – summaries can be reviewed/edited before Discord/PDF are finalized.
- **Cheap & simple first** – start with Neon + ARQ + S3-compatible storage. Add complexity only when needed.
- **Privacy-aware** – audio lives in object storage; delete objects when you only need text, and never expose provider keys to the browser. A scheduled retention policy is a future step.

---

Feature notes: [docs/features.md](docs/features.md).

Built for people who want meeting notes without the administrative drag.
```
