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
            parsed = json.loads(fenced_match.group(1))
            if isinstance(parsed, dict):
                return parsed
            raise ValueError("OpenAI returned JSON, but not a JSON object.")

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
            if isinstance(node, list):
                return [transform(item) for item in node]

            if not isinstance(node, dict):
                return node

            updated = {key: transform(value) for key, value in node.items()}

            if updated.get("type") == "object":
                properties = updated.get("properties")
                if isinstance(properties, dict):
                    updated["properties"] = {
                        key: transform(value) for key, value in properties.items()
                    }
                    updated["required"] = list(updated["properties"].keys())
                else:
                    updated["properties"] = {}
                    updated["required"] = []

                updated["additionalProperties"] = False

            if updated.get("type") == "array" and "items" in updated:
                updated["items"] = transform(updated["items"])

            if "anyOf" in updated and isinstance(updated["anyOf"], list):
                updated["anyOf"] = [transform(item) for item in updated["anyOf"]]

            if "oneOf" in updated and isinstance(updated["oneOf"], list):
                updated["oneOf"] = [transform(item) for item in updated["oneOf"]]

            if "allOf" in updated and isinstance(updated["allOf"], list):
                updated["allOf"] = [transform(item) for item in updated["allOf"]]

            if "$defs" in updated and isinstance(updated["$defs"], dict):
                updated["$defs"] = {
                    key: transform(value) for key, value in updated["$defs"].items()
                }

            if "definitions" in updated and isinstance(updated["definitions"], dict):
                updated["definitions"] = {
                    key: transform(value) for key, value in updated["definitions"].items()
                }

            return updated

        transformed = transform(schema)
        if not isinstance(transformed, dict):
            raise ValueError("Schema must be a JSON object.")
        return transformed

    def generate_json(self, *, model: str, system: str, prompt: str, schema: dict) -> dict[str, Any]:
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
