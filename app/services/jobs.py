"""Background job queue abstraction.

Production uses ARQ + Redis. Development and tests use an inline queue that runs
the same pipeline in a worker thread so behaviour stays close to production.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Protocol

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import Settings
from app.db.session import SessionLocal
from app.services.llm import CompleteJson
from app.services.pipeline import run_pipeline
from app.services.storage import Storage


class JobQueue(Protocol):
    async def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        job_id: str,
        max_tries: int = 3,
        wait: bool = True,
    ) -> str: ...


def pipeline_job_id(meeting_id: str, version: int = 1) -> str:
    return f"pipeline:{meeting_id}:{version}"


class InlineJobQueue:
    def __init__(
        self,
        settings: Settings,
        complete_json: Callable[[], CompleteJson],
        storage: Storage,
    ) -> None:
        self.settings = settings
        self._complete_json = complete_json
        self.storage = storage
        self._tasks: set[asyncio.Task] = set()

    async def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        job_id: str,
        max_tries: int = 3,
        wait: bool = True,
    ) -> str:
        if kind != "pipeline":
            raise ValueError(f"Unsupported inline job kind: {kind}")
        args = (
            payload["meeting_id"],
            SessionLocal,
            self.settings,
            self._complete_json(),
            self.storage,
            bool(payload.get("force", False)),
        )
        if wait:
            await asyncio.to_thread(run_pipeline, *args)
        else:
            task = asyncio.create_task(asyncio.to_thread(run_pipeline, *args))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return job_id


class ArqJobQueue:
    def __init__(self, pool: ArqRedis) -> None:
        self.pool = pool

    async def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        job_id: str,
        max_tries: int = 3,
        wait: bool = True,
    ) -> str:
        await self.pool.enqueue_job(
            kind,
            **payload,
            _job_id=job_id,
            _max_tries=max_tries,
        )
        return job_id


async def build_arq_queue(settings: Settings) -> ArqJobQueue:
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return ArqJobQueue(pool)
