# LoWi features

The browser UI is Streamlit on port 8501. `uvicorn` on port 8000 is only the API. `GET /` lists the useful links; `GET /docs` is the interactive API reference.

## Health

`GET /health` returns `{"status":"ok"}` after the process has created tables and the default local user.

Code: [app/api/routes/health.py](../app/api/routes/health.py)

## Meetings

`POST /meetings` creates a meeting with status `scheduled`. `GET /meetings` lists them newest first. `GET /meetings/{id}` returns the meeting plus its latest transcript, summary, and action items.

There is no login. Every row belongs to the seeded user `local@lowi.local`.

Code: [app/api/routes/meetings.py](../app/api/routes/meetings.py), [app/db/models.py](../app/db/models.py)

## Prep brief

`POST /meetings` with `"generate_prep": true` asks AgentRouter (`AGENTROUTER_PREP_MODEL`, default `deepseek-v4-flash`) for a short brief. Context is recent meetings and open action items. The text is stored on `meetings.prep_brief`.

Code: [app/services/prep.py](../app/services/prep.py)

## Upload and transcription

`POST /meetings/{id}/upload` saves the audio under `data/{meeting_id}/` and sets status `uploaded`. ElevenLabs Scribe v2 (`diarize=true`) runs in the background pipeline, then the transcript is stored (`raw_text`, `diarized_json`, `language`).

`GET /meetings/{id}/transcript` returns the latest transcript.

Code: [app/services/storage.py](../app/services/storage.py), [app/services/transcription.py](../app/services/transcription.py)

## Summary and action items

`POST /meetings/{id}/summarize` sends the transcript to AgentRouter (`AGENTROUTER_SUMMARY_MODEL`, default `claude-opus-4-8`). The JSON must include `decisions`, `action_items`, `open_questions`, `key_points`, and `narrative`. Action items for that meeting are replaced. `GET /action-items` lists open items across meetings.

Do not call `gpt-6-astra` or `claude-opus-5` with this token.

Code: [app/services/summarizer.py](../app/services/summarizer.py)

## PDF

`GET /meetings/{id}/pdf` renders the stored summary with WeasyPrint on each request. Nothing is uploaded to object storage.

Code: [app/services/pdf.py](../app/services/pdf.py)

## Discord

`POST /meetings/{id}/send-discord` posts a webhook embed (title, narrative, action items) to `DISCORD_WEBHOOK_URL` and sets status `sent`.

Code: [app/services/discord.py](../app/services/discord.py)

## Pipeline

Upload schedules `run_pipeline`: transcribe, summarize, then Discord if a webhook is set. Status moves `uploaded` → `transcribed` → `summarized` → `sent`. Any failure sets `failed` and stores the error on the meeting. PDF stays on demand.

The API uses FastAPI `BackgroundTasks`. [app/workers/tasks.py](../app/workers/tasks.py) is the same function behind ARQ if you later run a Redis worker.

Code: [app/services/pipeline.py](../app/services/pipeline.py)

## Streamlit

[frontend/app.py](../frontend/app.py) only calls the API. Create a meeting, pick one, upload audio, read the prep brief, transcript, and summary, then download a PDF or send Discord.

```bash
uv run streamlit run frontend/app.py
```

## Deferred

Zapier, R2/S3, Alembic, and auth stay out of this pass. See [zapier.md](zapier.md).
