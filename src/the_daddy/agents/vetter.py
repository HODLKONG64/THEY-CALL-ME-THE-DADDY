from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from ..config import Settings
from ..models import ExternalProposal, VettingDecision


class ExternalVetter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key)

    def _build_prompt(self, proposal: ExternalProposal, memory_snapshot: dict[str, Any]) -> str:
        proposal_json = json.dumps(proposal.model_dump(mode="json"), indent=2)
        memory_json = json.dumps(memory_snapshot, indent=2)[:12000]

        return f"""You are the external proposal vetting agent for a bounded defensive repository-maintenance system.

Your job:
- review the incoming external proposal
- decide whether it should be accepted
- assign a route: safe, branch, recommend, or reject
- explain the reason clearly
- assess risk as low, medium, or high
- assign a reputation delta
- provide concise notes

Rules:
- be conservative with unknown agents
- reject anything that suggests secrets handling, destructive shell actions, unbounded autonomy, or policy bypass
- use 'safe' only for clearly bounded, low-risk, repo-relevant suggestions
- use 'branch' for changes that may be useful but require human review
- use 'recommend' for useful ideas that should not be auto-applied
- use 'reject' for unsafe, irrelevant, or low-trust proposals

Return valid JSON only using this exact schema:
{{
  "accepted": true,
  "route": "safe",
  "reason": "short reason",
  "risk": "low",
  "reputation_delta": 1,
  "notes": ["note 1", "note 2"]
}}

Proposal:
{proposal_json}

Current memory snapshot:
{memory_json}
"""

    def vet(self, proposal: ExternalProposal, memory_snapshot: dict[str, Any]) -> VettingDecision:
        prompt = self._build_prompt(proposal, memory_snapshot)

        response = self.client.responses.create(
            model=self.settings.openai_model_vet,
            input=prompt,
        )

        text = response.output_text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise
            data = json.loads(text[start:end + 1])

        return VettingDecision.model_validate(data)
