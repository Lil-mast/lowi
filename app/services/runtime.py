"""Callables the API uses for external services. Tests replace this object."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.services.auth import AuthProvider, build_auth_provider
from app.services.jobs import InlineJobQueue, JobQueue
from app.services.llm import CompleteJson, build_complete_json
from app.services.realtime import RealtimeClient, build_realtime
from app.services.storage import Storage, build_storage


@dataclass
class Runtime:
    settings: Settings
    complete_json: CompleteJson
    auth: AuthProvider | None
    storage: Storage
    queue: JobQueue | None
    realtime: RealtimeClient


def build_runtime(settings: Settings) -> Runtime:
    complete_json = build_complete_json(settings)
    storage = build_storage(settings)
    runtime = Runtime(
        settings=settings,
        complete_json=complete_json,
        auth=build_auth_provider(settings),
        storage=storage,
        queue=None,
        realtime=build_realtime(settings),
    )
    if settings.job_backend == "inline":
        runtime.queue = InlineJobQueue(settings, lambda: runtime.complete_json, storage)
    return runtime
