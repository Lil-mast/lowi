"""Optional ARQ worker. The API enqueues the same pipeline when JOB_BACKEND=arq."""

from __future__ import annotations

from typing import ClassVar

from arq.connections import RedisSettings

from app.config import get_settings
from app.db.session import SessionLocal, configure_engine, init_db
from app.services.pipeline import run_pipeline
from app.services.runtime import build_runtime


async def startup(ctx: dict) -> None:
    settings = get_settings()
    configure_engine(settings.database_url)
    init_db(settings)
    runtime = build_runtime(settings)
    ctx["settings"] = settings
    ctx["complete_json"] = runtime.complete_json
    ctx["storage"] = runtime.storage


async def pipeline(ctx: dict, meeting_id: str, force: bool = False) -> None:
    run_pipeline(
        meeting_id,
        SessionLocal,
        ctx["settings"],
        ctx["complete_json"],
        ctx["storage"],
        force,
    )


class WorkerSettings:
    functions: ClassVar[list] = [pipeline]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 3
    job_timeout = 60 * 60
    keep_result = 60 * 60 * 24
