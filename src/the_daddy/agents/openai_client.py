from __future__ import annotations

import json
import re
from typing import Any, Optional

from openai import OpenAI

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
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        fenced_match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", cleaned, re.DOTALL)
        if fenced_match:
            return json.loads(fenced_match.group(1))

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

    def _strict_json_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        def transform(node: Any) -> Any:
            if isinstance(node, dict):
                updated = {key: transform(value) for key, value in node.items()}

                if updated.get("type") == "object":
                    updated["additionalProperties"] = False

                    properties = updated.get("properties")
                    if isinstance(properties, dict):
                        updated["properties"] = {
                            key: transform(value) for key, value in properties.items()
                        }

                if updated.get("type") == "array" and "items" in updated:
                    updated["items"] = transform(updated["items"])

                if "anyOf" in updated and isinstance(updated["anyOf"], list):
                    updated["anyOf"] = [transform(item) for item in updated["anyOf"]]

                if "oneOf" in updated and isinstance(updated["oneOf"], list):
                    updated["oneOf"] = [transform(item) for item in updated["oneOf"]]

                if "allOf" in updated and isinstance(updated["allOf"], list):
                    updated["allOf"] = [transform(item) for item in updated["allOf"]]

                return updated

            if isinstance(node, list):
                return [transform(item) for item in node]

            return node

        transformed = transform(schema)
        if not isinstance(transformed, dict):
            raise ValueError("Schema must be a JSON object.")
        return transformed

    def generate_json(self, *, model: str, system: str, prompt: str, schema: dict) -> dict:
        if not self.client:
            raise RuntimeError("OPENAI_API_KEY is not configured.")

        strict_schema = self._strict_json_schema(schema)

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
                    "schema": strict_schema,
                    "strict": True,
                }
            },
            timeout=self.settings.openai_timeout_seconds,
        )
        return self._parse_json_output(response.output_text)
