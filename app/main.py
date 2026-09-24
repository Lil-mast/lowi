"""FastAPI entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import calendar, health, meetings, transcripts
from app.config import Settings, get_settings
from app.db.session import configure_engine, init_db
from app.services.runtime import build_runtime


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_engine(settings.database_url)
    init_db(settings)
    app.state.runtime = build_runtime(settings)
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="LoWi", lifespan=lifespan)
    app.state.settings = settings or get_settings()
    app.include_router(health.router)
    app.include_router(calendar.router)
    app.include_router(meetings.router)
    app.include_router(transcripts.router)
    return app


app = create_app()
