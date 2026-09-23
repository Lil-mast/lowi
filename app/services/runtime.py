"""Callables the API uses for external services. Tests replace this object."""

from dataclasses import dataclass

from app.config import Settings
from app.services.llm import CompleteJson, build_complete_json


@dataclass
class Runtime:
    settings: Settings
    complete_json: CompleteJson


def build_runtime(settings: Settings) -> Runtime:
    return Runtime(settings=settings, complete_json=build_complete_json(settings))
