from __future__ import annotations

import json
from typing import Any, Optional

from openai import OpenAI

from ..config import Settings


class OpenAIJSONClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client: Optional[OpenAI] = OpenAI(api_key=settings.openai_api_key) if settings.has_openai else None

    def generate_json(self, *, model: str, system: str, prompt: str, schema: dict) -> dict:
        if not self.client:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        response = self.client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "structured_output",
                    "schema": schema,
                    "strict": True,
                }
            },
            timeout=self.settings.openai_timeout_seconds,
        )
        return json.loads(response.output_text)
