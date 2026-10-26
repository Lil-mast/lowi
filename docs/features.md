# LoWi features

The browser UI is Streamlit on port 8501. `uvicorn` on port 8000 is only the API. `GET /` lists the useful links; `GET /docs` is the interactive API reference.

## Health

`GET /health` returns `{"status":"ok"}` after the process has applied pending SQL migrations. The API does not create tables with `create_all`.

Code: [app/api/routes/health.py](../app/api/routes/health.py), [app/db/migrate.py](../app/db/migrate.py)

## Auth

`POST /auth/register` and `POST /auth/login` call Neon Auth (Managed Better Auth), link the external identity to a local `users` row, and return a random LoWi session token. Only the SHA-256 hash of the token is stored. Send it as `Authorization: Bearer <token>`.

`GET /auth/me` returns the current user. `POST /auth/logout` revokes the current session. `GET /auth/config` is public and tells the UI whether login and email verification are required.

When `REQUIRE_EMAIL_VERIFICATION=true`, registration returns `403` until the Neon Auth email OTP is confirmed. `POST /auth/resend-verification` sends a new code and `POST /auth/verify-email` verifies it, then returns a LoWi session. The Streamlit login screen shows a **Verify email** tab for this flow.

The API sends `UI_BASE_URL`'s origin to Neon Auth. That origin must be in the branch's Neon Auth trusted domains, or sign-up and sign-in return `Invalid origin`. The API also accepts a Managed Better Auth Ed25519 JWT directly and verifies it against the branch JWKS; issuer and audience default to the auth host origin.

`AUTH_MODE=dev` seeds `local@lowi.local` and skips login for local development. Production must use `AUTH_MODE=neon`.

Code: [app/services/auth.py](../app/services/auth.py), [app/services/sessions.py](../app/services/sessions.py), [app/api/routes/auth.py](../app/api/routes/auth.py)

## Meetings

`POST /meetings` creates a meeting with status `scheduled`. `GET /meetings` lists the current user's meetings newest first. `GET /meetings/{id}` returns the meeting plus its latest transcript, summary, and action items.

Every query is scoped to the authenticated user. Another user's meeting returns 404, not 403.

Code: [app/api/routes/meetings.py](../app/api/routes/meetings.py), [app/db/models.py](../app/db/models.py)

## Prep brief

`POST /meetings` with `"generate_prep": true` asks AgentRouter (`AGENTROUTER_PREP_MODEL`, default `deepseek-v4-flash`) for a short brief. Context is the agenda you typed, recent meetings, and open action items. The text is stored on `meetings.prep_brief`. The agenda itself is stored even when prep is off.

Code: [app/services/prep.py](../app/services/prep.py)

## Upload and transcription

`POST /meetings/{id}/upload` streams the audio into object storage and sets status `uploaded`. Local development uses `data/`; production uses an S3-compatible bucket (Neon Object Storage, R2, or AWS S3). Uploads are bounded by `MAX_UPLOAD_MB`, checked by extension, and recorded with size and SHA-256.

The pipeline downloads the object, runs ElevenLabs Scribe v2 (`diarize=true`), and stores the transcript (`raw_text`, `diarized_json`, `language`).

`GET /meetings/{id}/transcript` returns the latest transcript.

Code: [app/services/storage.py](../app/services/storage.py), [app/services/transcription.py](../app/services/transcription.py)

## Summary and action items

`POST /meetings/{id}/summarize` sends the transcript to AgentRouter (`AGENTROUTER_SUMMARY_MODEL`, default `claude-opus-4-8`). Long transcripts are split into part notes and merged into one final summary. The JSON must include `decisions`, `action_items`, `open_questions`, `key_points`, and `narrative`. Action items are reconciled by a stable key, so a completed item keeps its status when the summary is regenerated; missing items are removed. `GET /action-items` lists the current user's open items across meetings.

Do not call `gpt-6-astra` or `claude-opus-5` with this token.

Code: [app/services/summarizer.py](../app/services/summarizer.py)

## PDF

`GET /meetings/{id}/pdf` renders the stored summary with WeasyPrint on each request. Nothing is uploaded to object storage.

Code: [app/services/pdf.py](../app/services/pdf.py)

## Discord

`POST /meetings/{id}/send-discord` posts a webhook embed (title, narrative, action items) to `DISCORD_WEBHOOK_URL` and sets status `sent`.

Code: [app/services/discord.py](../app/services/discord.py)

## Pipeline and jobs

Upload enqueues a durable pipeline job. In production `JOB_BACKEND=arq` uses Redis and a separate ARQ worker; in development and tests `JOB_BACKEND=inline` runs the same function in a worker thread. The API never relies on `BackgroundTasks` for pipeline work.

The pipeline moves `uploaded` → `transcribed` → `summarized` → `sent`. Failures set `failed`, store a safe message on the meeting, and keep the full error on `pipeline_runs` for operators. Pipeline runs are idempotent per meeting version; retries use `_max_tries=3`.

Code: [app/services/pipeline.py](../app/services/pipeline.py), [app/services/jobs.py](../app/services/jobs.py), [app/workers/tasks.py](../app/workers/tasks.py)

## Google Calendar

Read-only. `GET /calendar/connect` starts OAuth. `GET /calendar/callback` stores the token under `DATA_DIR`. `GET /calendar/events` requires auth and returns the next ten primary-calendar events, or `{configured, connected, events}` when Google is not set up yet. "Prep this meeting" in the UI creates a LoWi meeting from the event title, time, and description (used as the agenda).

The connect and callback routes are public because they are browser redirects; protect the OAuth `state` value before exposing this to multiple real users.

Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI`. On Render, also set `GOOGLE_REFRESH_TOKEN` so the connection survives a restart.

Code: [app/services/calendar.py](../app/services/calendar.py), [app/api/routes/calendar.py](../app/api/routes/calendar.py)

## Streamlit

[frontend/app.py](../frontend/app.py) only calls the API. It shows a login gate when `/auth/config` says auth is required, stores the LoWi token in a cookie, and sends it on every request. Create a meeting, pick one, upload audio, read the prep brief, transcript, and summary, then download a PDF or send Discord.

```bash
uv run streamlit run frontend/app.py
```

## Live meeting capture

`POST /meetings/{id}/live/ticket` returns a short-lived signed ticket and a `wss://` URL. The Streamlit live view opens that URL, captures microphone or shared-tab audio, downsamples it to 16 kHz PCM16, and sends it over the WebSocket. The API proxies the audio to ElevenLabs Scribe Realtime using the server-side `xi-api-key`; the key never reaches the browser.

While recording, the page shows partial and committed text. On stop, the API writes the captured PCM to a WAV, stores it, saves the live transcript, and queues the normal pipeline. That pipeline runs batch Scribe v2 with `diarize=true`, replaces the live transcript with the diarized one, and summarizes. The live session row tracks `recording`, `finalizing`, `completed`, or `failed`.

Constraints:

- The browser needs HTTPS (or localhost) for microphone access. Shared-tab audio requires the browser's “Share tab audio” option.
- No bot joins Zoom, Meet, or Teams in this version. The browser is the capture device.
- Keep the live tab open. A dropped socket ends the session; audio already received is still finalized.
- `PUBLIC_BASE_URL` must be the public API origin, including any path prefix, or the browser will open the wrong WebSocket.
- Tickets expire after `LIVE_TICKET_TTL_SECONDS` (default 15 minutes). Reopen the live view to get a new one.
- The live realtime model does not return speaker labels. Diarization comes from the batch pass after stop.

Code: [app/api/routes/live.py](../app/api/routes/live.py), [app/services/live.py](../app/services/live.py), [app/services/realtime.py](../app/services/realtime.py), [frontend/live.py](../frontend/live.py)

## Deferred

Zapier stays out of this pass. See [zapier.md](zapier.md).
