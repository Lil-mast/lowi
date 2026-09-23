"""Optional ARQ worker. The API uses BackgroundTasks; this wraps the same pipeline."""

from typing import ClassVar

from arq.connections import RedisSettings

from app.config import get_settings
from app.db.session import SessionLocal, configure_engine, init_db
from app.services.llm import build_complete_json
from app.services.pipeline import run_pipeline


async def startup(ctx: dict) -> None:
    settings = get_settings()
    configure_engine(settings.database_url)
    init_db(settings)
    ctx["settings"] = settings
    ctx["complete_json"] = build_complete_json(settings)


async def pipeline(ctx: dict, meeting_id: str) -> None:
    run_pipeline(meeting_id, SessionLocal, ctx["settings"], ctx["complete_json"])


class WorkerSettings:
    functions: ClassVar[list] = [pipeline]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
