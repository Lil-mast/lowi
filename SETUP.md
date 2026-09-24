# Setup

Local run of the LoWi API and the Streamlit UI. Feature behavior is in [docs/features.md](docs/features.md).

## Requirements

- [uv](https://docs.astral.sh/uv/) (this repo does not use pip)
- Python 3.14 (uv reads `.python-version` and can install it)
- Optional: a [Neon](https://neon.tech) Postgres database. Without `DATABASE_URL`, the API uses `sqlite:///./data/lowi.db`.
- Optional system libraries for PDF rendering (WeasyPrint): Cairo, Pango, and GDK-PixBuf. On Arch: `sudo pacman -S cairo pango gdk-pixbuf2`.

## Install

```bash
uv sync --group frontend --group dev
cp .env.example .env
```

`frontend` installs Streamlit. `dev` installs pytest and ruff. The API dependencies, including `psycopg`, come from the main group.

## Configure `.env`

Fill in the keys you have. Leave a value empty to skip that step. The API still starts.

| Variable | Required for | Notes |
|---|---|---|
| `DATABASE_URL` | Neon | `postgresql://...` is fine. The app rewrites it to the psycopg driver. Omit the line to use local SQLite. |
| `ELEVENLABS_API_KEY` | Transcription | Scribe v2 with diarization |
| `AGENTROUTER_API_KEY` | Prep and summaries | Create a token at [agentrouter.org/console/token](https://agentrouter.org/console/token) |
| `AGENTROUTER_BASE_URL` | LLM calls | `https://agentrouter.org/v1` |
| `AGENTROUTER_SUMMARY_MODEL` | Summaries | `claude-opus-4-8` |
| `AGENTROUTER_PREP_MODEL` | Prep briefs | `deepseek-v4-flash` |
| `DISCORD_WEBHOOK_URL` | Discord delivery | Webhook URL for the target channel |
| `DATA_DIR` | Audio files | Defaults to `data/` (gitignored) |
| `REDIS_URL` | Optional ARQ worker | The API does not need Redis. Jobs run in-process. |

Do not set `AGENTROUTER_SUMMARY_MODEL` or `AGENTROUTER_PREP_MODEL` to `gpt-6-astra` or `claude-opus-5`. This token cannot use those models.

AgentRouter refills quota twice a day: 10:00 and 19:00 Beijing time (02:00 and 11:00 UTC, 05:00 and 14:00 in UTC+3).

Tables are created on API startup. There is no Alembic step.

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

Streamlit reads `LOWI_API_URL` when the API is not on port 8000. The orange theme is `frontend/.streamlit/config.toml`. Restart Streamlit after changing it.

## Check

```bash
uv run pytest
```

## Optional worker

Redis plus ARQ runs the same pipeline outside the API process. Skip this for local use.

```bash
uv run arq app.workers.tasks.WorkerSettings
```
