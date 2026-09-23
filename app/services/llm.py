"""AgentRouter chat client (OpenAI-compatible)."""

import json
from collections.abc import Callable

from openai import OpenAI

from app.config import Settings

CompleteJson = Callable[[str, str, str], dict]


def build_complete_json(settings: Settings) -> CompleteJson:
    client = OpenAI(
        api_key=settings.agentrouter_api_key or "missing",
        base_url=settings.agentrouter_base_url,
    )

    def complete_json(model: str, system: str, user: str) -> dict:
        if not settings.agentrouter_api_key:
            raise RuntimeError("AGENTROUTER_API_KEY is not set")
        completion = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = completion.choices[0].message.content or "{}"
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise TypeError("Model response was not a JSON object")
        return parsed

    return complete_json
