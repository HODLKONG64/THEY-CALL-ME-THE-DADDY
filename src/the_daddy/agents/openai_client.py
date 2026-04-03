from __future__ import annotations

import json
import re
from typing import Any, Optional

from openai import BadRequestError, OpenAI

from ..config import Settings


class OpenAIJSONClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client: Optional[OpenAI] = OpenAI(api_key=settings.openai_api_key) if settings.has_openai else None

    def _parse_json_output(self, text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("OpenAI returned empty output; expected JSON.")

        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
            raise ValueError("OpenAI returned JSON, but not a JSON object.")
        except json.JSONDecodeError:
            pass

        fenced_match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", cleaned, re.DOTALL)
        if fenced_match:
            parsed = json.loads(fenced_match.group(1))
            if isinstance(parsed, dict):
                return parsed
            raise ValueError("OpenAI returned fenced JSON, but not a JSON object.")

        decoder = json.JSONDecoder()
        for start_index, char in enumerate(cleaned):
            if char not in "[{":
                continue
            try:
                parsed, _ = decoder.raw_decode(cleaned[start_index:])
                if isinstance(parsed, dict):
                    return parsed
                raise ValueError("OpenAI returned JSON, but not a JSON object.")
            except json.JSONDecodeError:
                continue

        raise ValueError("Failed to parse JSON object from OpenAI response output.")

    def _generate_json_with_schema(self, *, model: str, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
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
        return self._parse_json_output(response.output_text)

    def _generate_json_prompt_only(self, *, model: str, system: str, prompt: str) -> dict[str, Any]:
        if not self.client:
            raise RuntimeError("OPENAI_API_KEY is not configured.")

        response = self.client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        prompt
                        + "\n\nReturn valid JSON only. Do not wrap the JSON in markdown fences."
                    ),
                },
            ],
            timeout=self.settings.openai_timeout_seconds,
        )
        return self._parse_json_output(response.output_text)

    def generate_json(self, *, model: str, system: str, prompt: str, schema: dict) -> dict[str, Any]:
        if not self.client:
            raise RuntimeError("OPENAI_API_KEY is not configured.")

        try:
            return self._generate_json_with_schema(
                model=model,
                system=system,
                prompt=prompt,
                schema=schema,
            )
        except BadRequestError as exc:
            text = str(exc)
            if "invalid_json_schema" not in text and "Invalid schema for response_format" not in text:
                raise

        return self._generate_json_prompt_only(
            model=model,
            system=system,
            prompt=prompt,
        )
