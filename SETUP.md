# Setup

Local run of the LoWi API and the Streamlit UI. Feature behavior is in [docs/features.md](docs/features.md).

## Requirements

- [uv](https://docs.astral.sh/uv/) (this repo does not use pip)
- Python 3.14 (uv reads `.python-version` and can install it)
- Optional: a [Neon](https://neon.tech) Postgres database. Without `DATABASE_URL`, the API uses `sqlite:///./data/lowi.db`.
- Optional: Redis for durable jobs. Without it, `JOB_BACKEND=inline` runs jobs in the API process.
- Optional system libraries for PDF rendering (WeasyPrint): Cairo, Pango, and GDK-PixBuf. On Arch: `sudo pacman -S cairo pango gdk-pixbuf2`.

## Install

```bash
uv sync --group frontend --group dev
cp .env.example .env
```

`frontend` installs Streamlit. `dev` installs pytest and ruff. The API dependencies, including `psycopg` and `boto3`, come from the main group.

## Configure `.env`

Fill in the keys you have. Leave a value empty to skip that step. The API still starts in development mode.

| Variable | Required for | Notes |
|---|---|---|
| `APP_ENV` | Mode | `development` locally; `production` on Render. |
| `DATABASE_URL` | Neon | `postgresql://...` is fine. The app rewrites it to the psycopg driver. Omit the line to use local SQLite. |
| `ELEVENLABS_API_KEY` | Transcription | Scribe v2 with diarization |
| `AGENTROUTER_API_KEY` | Prep and summaries | Create a token at [agentrouter.org/console/token](https://agentrouter.org/console/token) |
| `AGENTROUTER_BASE_URL` | LLM calls | `https://agentrouter.org/v1` |
| `AGENTROUTER_SUMMARY_MODEL` | Summaries | `claude-opus-4-8` |
| `AGENTROUTER_PREP_MODEL` | Prep briefs | `deepseek-v4-flash` |
| `DISCORD_WEBHOOK_URL` | Discord delivery | Webhook URL for the target channel |
| `DATA_DIR` | Local audio | Defaults to `data/` (gitignored) |
| `AUTH_MODE` | Login | `dev` for local development; `neon` for Neon Auth. Production rejects anything other than `neon`. |
| `NEON_AUTH_BASE_URL` | Neon Auth | The `base_url` returned when Managed Better Auth is enabled, e.g. `https://ep-xxx.neonauth.us-east-1.aws.neon.tech/neondb/auth` |
| `NEON_AUTH_JWKS_URL` | JWT verification | The `jwks_url` returned by Neon, usually `<base_url>/.well-known/jwks.json` |
| `NEON_AUTH_ISSUER` | JWT verification | Optional. Defaults to the origin of `NEON_AUTH_BASE_URL` (`https://ep-xxx...`). |
| `NEON_AUTH_AUDIENCE` | JWT verification | Optional. Defaults to the origin of `NEON_AUTH_BASE_URL`. |
| `REQUIRE_EMAIL_VERIFICATION` | Login | `true` in production. Registration returns a verification prompt until Neon Auth's email OTP is confirmed. |
| `UI_BASE_URL` | Neon Auth | Public Streamlit origin. Add this exact origin to Neon Auth trusted domains. |
| `SECRET_KEY` | Sessions/live tickets | Set to a random value of at least 32 characters; required in production. |
| `SESSION_TTL_DAYS` | Login | Local LoWi session lifetime. Defaults to 30. |
| `JOB_BACKEND` | Pipeline | `inline` locally; `arq` in production. |
| `REDIS_URL` | ARQ worker | Required when `JOB_BACKEND=arq`. |
| `STORAGE_BACKEND` | Audio | `local` locally; `s3` in production. |
| `S3_*` | Object storage | Bucket, region, endpoint, access key, secret. Works with Neon Object Storage, Cloudflare R2, and AWS S3. |
| `MAX_UPLOAD_MB` | Upload limit | Defaults to 500. |
| `ELEVENLABS_REALTIME_MODEL` | Live capture | Defaults to `scribe_v2_realtime`. |
| `LIVE_MAX_MINUTES` | Live capture | Defaults to 240. |
| `LIVE_TICKET_TTL_SECONDS` | Live capture | Defaults to 900. |
| `PUBLIC_BASE_URL` | Live capture, links | Must be the public API origin; the live WebSocket is built from it. |

Do not set `AGENTROUTER_SUMMARY_MODEL` or `AGENTROUTER_PREP_MODEL` to `gpt-6-astra` or `claude-opus-5`. This token cannot use those models.

AgentRouter refills quota twice a day: 10:00 and 19:00 Beijing time (02:00 and 11:00 UTC, 05:00 and 14:00 in UTC+3).

## Database migrations

Startup applies pending SQL migrations from `app/db/migrations` and records them in `schema_migrations`. Existing databases created by the old `create_all` path are baselined automatically. There is no Alembic step and no manual SQL step.

Never edit a migration that has already been applied; add a new numbered file instead.

## Enable auth

Local development uses `AUTH_MODE=dev`, which seeds `local@lowi.local` and skips login. To use real auth:

1. Enable Managed Better Auth on the Neon branch (Neon console → Auth, or `provision_neon_auth` through the Neon MCP server).
2. Copy the returned `base_url` and `jwks_url` into `NEON_AUTH_BASE_URL` and `NEON_AUTH_JWKS_URL`.
3. Add the public Streamlit origin to Neon Auth trusted domains, for example `http://127.0.0.1:8501` locally and `https://<lowi-ui host>` in production. The API sends this origin as the `Origin` header; without it Neon Auth rejects sign-up and sign-in with `Invalid origin`.
4. Set `UI_BASE_URL` to that same origin, set `AUTH_MODE=neon`, and set `REQUIRE_EMAIL_VERIFICATION=true` if Neon Auth requires email verification.
5. Restart the API and Streamlit. The UI will show the login screen.
6. Register your real account, enter the code from the verification email in the **Verify email** tab, then move any legacy rows:

```bash
uv run python scripts/claim_legacy_data.py --email you@example.com
uv run python scripts/claim_legacy_data.py --email you@example.com --apply
```

The script is idempotent. The first run is a dry run.

Leave `NEON_AUTH_ISSUER` and `NEON_AUTH_AUDIENCE` empty unless you have a reason to override them. Managed Better Auth signs Ed25519 JWTs with the issuer and audience set to the auth host origin, not the full `/neondb/auth` path. The API derives both from `NEON_AUTH_BASE_URL`.

The Neon `production` branch already has Managed Better Auth enabled. Its `base_url` and `jwks_url` are pre-filled in `render.yaml`, and `https://lowi-ui.onrender.com` is the trusted origin. Email verification is enabled with OTP delivery on sign-up. If Render assigns a different UI hostname, add that exact origin in Neon Auth and update `UI_BASE_URL` in `render.yaml`.

For another branch, enable the same settings in the Neon Console under **Auth → Configuration**, or with the CLI:

```bash
neon neon-auth config email-password update \
  --project-id <project-id> --branch <branch> \
  --require-email-verification --send-verification-email-on-sign-up
```

The shared Neon email sender (`auth@mail.myneon.app`) is fine for initial testing. Configure a dedicated SMTP provider before relying on verification or password-reset email at volume.

## Run

Use two terminals from the repo root.

```bash
uv run uvicorn app.main:app --reload
```

```bash
uv run streamlit run frontend/app.py
```

| URL | What it is |
|---|---|
| http://127.0.0.1:8000/ | API index. This is not the app UI. |
| http://127.0.0.1:8000/docs | Interactive API docs |
| http://127.0.0.1:8000/health | `{"status":"ok"}` |
| http://127.0.0.1:8501 | Streamlit UI |

Streamlit reads `LOWI_API_URL` when the API is not on port 8000. The orange theme is `.streamlit/config.toml` at the repo root. Restart Streamlit after changing it.

## Live capture

Open a meeting in Streamlit and click **Record live**. Choose **Microphone** or **Shared tab audio**, then **Start recording**.

- Localhost is a secure context, so the microphone works over `http://127.0.0.1:8501`.
- The deployed UI must be HTTPS for microphone access.
- Shared-tab audio only works when the browser offers **Share tab audio** (Chrome and Edge do). Meeting apps must play audio in the tab; headphones keep the audio out of the microphone capture.
- `PUBLIC_BASE_URL` must point at the API that the browser can reach. In production this is the public API URL, not an internal Render hostname.
- The ElevenLabs key stays on the API. The browser only receives a 15-minute signed ticket scoped to one meeting.
- Stopping queues batch diarization and the summary. The live transcript is available immediately; the diarized transcript and summary replace it when the pipeline finishes.
- Finalizing writes a temporary PCM file and a WAV under `DATA_DIR`. Budget roughly twice the raw PCM size of the longest allowed meeting: 16 kHz mono PCM16 is about 115 MB per hour. Lower `LIVE_MAX_MINUTES` if the host has a small ephemeral disk.

Code: `frontend/live.py`, `app/api/routes/live.py`, `app/services/live.py`.

## Check

```bash
uv run ruff check .
uv run python -m pytest -q
```

Use `python -m pytest` rather than the `pytest` script so the project virtualenv is used consistently.

## Render

`render.yaml` defines a Redis instance, an API web service, a worker service, and the Streamlit UI from the same Docker image. Shared backend configuration lives in the `lowi-backend` environment group, so the API and worker receive the same generated `SECRET_KEY`. Render fills `PUBLIC_BASE_URL` from the API's `RENDER_EXTERNAL_URL` and `LOWI_API_URL` from the API service; `UI_BASE_URL` is set to `https://lowi-ui.onrender.com`.

1. Create a Neon database and copy its connection string. The Render disk is ephemeral, so do not use SQLite there.
2. Managed Better Auth is already enabled on the Neon `production` branch. Its `base_url` / `jwks_url` are in `render.yaml`, and `https://lowi-ui.onrender.com` is trusted. If Render assigns a different UI hostname, add it to Neon Auth trusted domains and update `UI_BASE_URL` in the `lowi-backend` group.
3. Create an S3-compatible bucket (Neon Object Storage is the default choice) and copy its endpoint and keys.
4. In Google Cloud, create an OAuth client and add the public API callback, `https://<lowi-api host>/calendar/callback`. This is optional unless you use Calendar.
5. Connect the GitHub repo in Render and apply the blueprint. Fill the `lowi-backend` secrets once: `DATABASE_URL`, `ELEVENLABS_API_KEY`, `AGENTROUTER_API_KEY`, `DISCORD_WEBHOOK_URL`, `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, and `S3_SECRET_ACCESS_KEY`. Do not set `SECRET_KEY`; Render generates it for the group. Fill the API-only Google values separately if you use Calendar.
6. Confirm email verification is enabled in Neon Auth. The production branch already sends an OTP on sign-up; configure a dedicated SMTP provider before public launch.
7. Connect Calendar once locally (or on the API host). Copy `refresh_token` from `data/google_token.json` into `GOOGLE_REFRESH_TOKEN` so a restart does not drop the connection.

Health check for the API is `GET /health`. The worker runs `arq app.workers.tasks.WorkerSettings`.

## Optional local worker

Redis plus ARQ runs the same pipeline outside the API process:

```bash
uv run arq app.workers.tasks.WorkerSettings
```

Set `JOB_BACKEND=arq` in the API environment too, otherwise uploads run inline.
