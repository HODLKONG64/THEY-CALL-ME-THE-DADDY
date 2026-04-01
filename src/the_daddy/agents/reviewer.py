from __future__ import annotations

import json
from pathlib import Path

from ..config import Settings
from ..models import ArchitectureReview
from ..prompts import ARCHITECTURE_REVIEW_SYSTEM
from .openai_client import OpenAIJSONClient


REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "diagnosis": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "weaknesses": {"type": "array", "items": {"type": "string"}},
        "recommendations": {"type": "array", "items": {"type": "string"}},
        "backlog_items": {"type": "array", "items": {"type": "string"}},
        "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["diagnosis", "strengths", "weaknesses", "recommendations", "backlog_items", "risk_level"],
}


class WakeReviewer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAIJSONClient(settings)

    def review(self, *, memory_snapshot: dict, repo_root: Path, recent_summary: str) -> ArchitectureReview:
        prompt = (
            f"Repo root: {repo_root}\n"
            f"Recent summary: {recent_summary or 'None'}\n"
            f"Memory snapshot: {json.dumps(memory_snapshot)[:50000]}"
        )
        data = self.client.generate_json(
            model=self.settings.openai_model_review,
            system=ARCHITECTURE_REVIEW_SYSTEM,
            prompt=prompt,
            schema=REVIEW_SCHEMA,
        )
        return ArchitectureReview.model_validate(data)
