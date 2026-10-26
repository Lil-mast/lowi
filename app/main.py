"""FastAPI entrypoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import auth, calendar, health, live, meetings, transcripts
from app.config import Settings, get_settings, validate_settings
from app.db.session import configure_engine, init_db
from app.services.jobs import ArqJobQueue, build_arq_queue
from app.services.runtime import build_runtime

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    validate_settings(settings)
    logging.basicConfig(level=settings.log_level.upper())
    configure_engine(settings.database_url)
    init_db(settings)
    runtime = build_runtime(settings)
    if settings.job_backend == "arq":
        runtime.queue = await build_arq_queue(settings)
    app.state.runtime = runtime
    logger.info(
        "LoWi started in %s auth mode with %s jobs",
        settings.auth_mode,
        settings.job_backend,
    )
    yield
    if isinstance(runtime.queue, ArqJobQueue):
        await runtime.queue.pool.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="LoWi", lifespan=lifespan)
    app.state.settings = settings or get_settings()
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(calendar.router)
    app.include_router(live.router)
    app.include_router(meetings.router)
    app.include_router(transcripts.router)
    return app


app = create_app()
