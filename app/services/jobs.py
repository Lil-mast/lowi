"""Background job queue abstraction.

Production uses ARQ + Redis. Development and tests use an inline queue that runs
the same pipeline in a worker thread so behaviour stays close to production.
"""

from __future__ import annotations

import asyncio
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
    ) -> str: ...


def pipeline_job_id(meeting_id: str, version: int = 1) -> str:
    return f"pipeline:{meeting_id}:{version}"


class InlineJobQueue:
    def __init__(self, settings: Settings, complete_json: CompleteJson, storage: Storage) -> None:
        self.settings = settings
        self.complete_json = complete_json
        self.storage = storage

    async def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        job_id: str,
        max_tries: int = 3,
    ) -> str:
        if kind == "pipeline":
            await asyncio.to_thread(
                run_pipeline,
                payload["meeting_id"],
                SessionLocal,
                self.settings,
                self.complete_json,
                self.storage,
                bool(payload.get("force", False)),
            )
        else:
            raise ValueError(f"Unsupported inline job kind: {kind}")
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
