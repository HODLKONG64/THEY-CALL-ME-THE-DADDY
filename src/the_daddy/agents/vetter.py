from __future__ import annotations

import json

from ..config import Settings
from ..models import ExternalProposal, VetDecision
from ..prompts import VET_SYSTEM
from .openai_client import OpenAIJSONClient


VET_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "accepted": {"type": "boolean"},
        "route": {"type": "string", "enum": ["reject", "stage", "accept"]},
        "reason": {"type": "string"},
        "risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "reputation_delta": {"type": "integer"},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["accepted", "route", "reason", "risk", "reputation_delta", "notes"],
}


class ExternalVetter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAIJSONClient(settings)

    def vet(self, proposal: ExternalProposal, memory_snapshot: dict) -> VetDecision:
        prompt = (
            f"Proposal: {proposal.model_dump_json()}\n"
            f"Memory snapshot: {json.dumps(memory_snapshot)[:30000]}"
        )
        data = self.client.generate_json(
            model=self.settings.openai_model_vet,
            system=VET_SYSTEM,
            prompt=prompt,
            schema=VET_SCHEMA,
        )
        return VetDecision.model_validate(data)
