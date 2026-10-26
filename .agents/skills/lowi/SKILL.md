---
name: lowi
description: How LoWi is built. Use when changing meetings, prep, transcription, summaries, PDF, Discord, auth, jobs, storage, live capture, or the Streamlit UI.
---

# LoWi

API-first meeting notes. FastAPI owns the work. Streamlit only calls HTTP.

Read [docs/features.md](../../../docs/features.md) before editing a feature.

## Rules

- Auth is Neon Auth (Managed Better Auth). Python talks to its REST API and verifies Neon JWTs in `app/services/auth.py`. LoWi then issues opaque local session tokens (`app/services/sessions.py`); never proxy Neon cookies through Streamlit and never put provider API keys in the browser.
- Neon Auth requires an `Origin` header. The API sends `UI_BASE_URL`'s origin; that exact origin must be in the branch's trusted domains. JWT issuer and audience are the auth host origin, not the `/neondb/auth` path.
- All user data must go through `get_current_user` / `get_meeting`. Never fetch a meeting by id without `meeting.user_id == user.id`.
- Use plain SQL migrations in `app/db/migrations` and `run_migrations`. Never add Alembic, never call `Base.metadata.create_all`, and never edit a migration that has been applied.
- Background jobs go through `app/services/jobs.py`: ARQ + Redis in production, inline in development/tests. Do not add ad-hoc `BackgroundTasks` for pipelines.
- Storage goes through `app/services/storage.py`: local disk in development/tests, S3-compatible in production. Do not hardcode filesystem paths in routes or services.
- Live audio goes browser → API WebSocket → ElevenLabs. The browser gets a short-lived signed ticket, never the ElevenLabs key. Keep finalization and batch diarization in the pipeline, not in the WebSocket handler's request path.
- LLM calls go through AgentRouter (`app/services/llm.py`). Summary model is `claude-opus-4-8`. Prep model is `deepseek-v4-flash`. Do not use `gpt-6-astra` or `claude-opus-5`.
- Postgres URLs are rewritten to `postgresql+psycopg://` in `normalize_database_url`.
- Tests use in-memory SQLite via `create_app(Settings(...))` and never require Neon, Redis, S3, ElevenLabs, or AgentRouter. Inject fakes through `app.state.runtime`.
- `GET /` must stay a 200. The API root is not the UI.
- Production must set `APP_ENV=production`, `AUTH_MODE=neon`, `JOB_BACKEND=arq`, `STORAGE_BACKEND=s3`, and an `https://` `PUBLIC_BASE_URL`; startup validation rejects anything else.

## Where each feature lives

| Feature | Code | HTTP |
|---|---|---|
| Health and index | `app/api/routes/health.py` | `GET /`, `GET /health` |
| Auth | `app/services/auth.py`, `app/api/routes/auth.py` | `POST /auth/register`, `/auth/login`, `/auth/logout`; `GET /auth/me`, `/auth/config` |
| Meetings | `app/api/routes/meetings.py` | `POST/GET /meetings`, `GET /meetings/{id}` |
| Prep | `app/services/prep.py` | `generate_prep` on create; agenda is included |
| Calendar | `app/services/calendar.py` | `GET /calendar/connect`, `/calendar/callback`, `/calendar/events` |
| Audio upload | `app/services/storage.py` | `POST /meetings/{id}/upload` |
| Transcription | `app/services/transcription.py` | `GET /meetings/{id}/transcript` |
| Summary | `app/services/summarizer.py` | `POST /meetings/{id}/summarize`, `GET /action-items` |
| PDF | `app/services/pdf.py` | `GET /meetings/{id}/pdf` |
| Discord | `app/services/discord.py` | `POST /meetings/{id}/send-discord` |
| Pipeline | `app/services/pipeline.py`, `app/services/jobs.py` | queued after upload or live stop |
| Live capture | `app/api/routes/live.py`, `app/services/live.py`, `app/services/realtime.py` | `POST /meetings/{id}/live/ticket`; `WS /meetings/{id}/live` |
| Live UI | `frontend/live.py` | Streamlit CCv2 component |
| Migrations | `app/db/migrate.py`, `app/db/migrations/*.sql` | startup |
| UI | `frontend/app.py` | Streamlit, no business logic |

## Auth flow

1. Streamlit sends email/password to `POST /auth/login`.
2. The API calls Neon Auth, links the Neon user to a local `users` row, and returns a random LoWi session token. Only its SHA-256 hash is stored.
3. Streamlit sends `Authorization: Bearer <token>` on every API call.
4. The API resolves the local session first; it only falls back to Neon JWT verification for tokens that are not local sessions.
5. Streamlit persists the local token in a cookie; logout revokes the session row.

## Streamlit

Follow `.agents/skills/developing-with-streamlit`. Sentence case, Material icons, `st.form` for create, sidebar for the meeting picker only, bordered containers for sections. Theme lives in `.streamlit/config.toml` at the repo root. The login gate must render before any meeting data and call `/auth/config` so local `AUTH_MODE=dev` still works without a login.
