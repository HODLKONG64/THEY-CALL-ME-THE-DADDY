from __future__ import annotations

import json

from ..config import Settings
from ..models import DiagnosticPlan
from ..prompts import DIAGNOSIS_SYSTEM
from .openai_client import OpenAIJSONClient


DIAGNOSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "diagnosis": {"type": "string"},
        "root_cause": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "why_this_failed": {"type": "array", "items": {"type": "string"}},
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string"},
                    "operation": {"type": "string", "enum": ["replace_file", "regex_replace"]},
                    "description": {"type": "string"},
                    "new_content": {"type": ["string", "null"]},
                    "pattern": {"type": ["string", "null"]},
                    "replacement": {"type": ["string", "null"]},
                },
                "required": ["path", "operation", "description", "new_content", "pattern", "replacement"],
            },
        },
        "post_fix_checks": {"type": "array", "items": {"type": "string"}},
        "test_suggestions": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "diagnosis",
        "root_cause",
        "confidence",
        "why_this_failed",
        "changes",
        "post_fix_checks",
        "test_suggestions",
    ],
}


class Diagnoser:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAIJSONClient(settings)

    def diagnose(self, *, command: str, output: str, files: list[dict], prior_attempts: list[dict]) -> DiagnosticPlan:
        prompt = (
            f"Command: {command}\n"
            f"Output: {output[:80000]}\n"
            f"Files: {json.dumps(files)[:80000]}\n"
            f"Prior attempts: {json.dumps(prior_attempts)[:40000]}"
        )
        data = self.client.generate_json(
            model=self.settings.openai_model_main,
            system=DIAGNOSIS_SYSTEM,
            prompt=prompt,
            schema=DIAGNOSIS_SCHEMA,
        )
        return DiagnosticPlan.model_validate(data)
