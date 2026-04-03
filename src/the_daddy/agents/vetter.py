from __future__ import annotations

from typing import Any

from ..config import Settings
from ..models import ExternalProposal, VettingDecision
from .openai_client import OpenAIJSONClient


class ExternalVetter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAIJSONClient(settings) if settings.has_openai else None

    def _build_prompt(self, proposal: ExternalProposal, memory_snapshot: dict[str, Any]) -> str:
        proposal_json = proposal.model_dump_json(indent=2)
        memory_json = str(memory_snapshot)
        if len(memory_json) > 12000:
            memory_json = memory_json[:12000]

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

    def _fallback_decision(self, reason: str) -> VettingDecision:
        return VettingDecision(
            accepted=False,
            route="reject",
            reason=reason,
            risk="high",
            reputation_delta=0,
            notes=["Fallback vetting decision used because model output was unavailable or invalid."],
        )

    def vet(self, proposal: ExternalProposal, memory_snapshot: dict[str, Any]) -> VettingDecision:
        if self.client is None:
            return self._fallback_decision("OpenAI client unavailable.")

        prompt = self._build_prompt(proposal, memory_snapshot)

        try:
            data = self.client.generate_json(
                model=self.settings.openai_model_vet,
                system="You are a strict JSON-only vetting agent. Return only a JSON object matching the required schema.",
                prompt=prompt,
                schema=VettingDecision.model_json_schema(),
            )
            return VettingDecision.model_validate(data)
        except Exception as exc:
            return self._fallback_decision(f"Vetting model call failed: {type(exc).__name__}")
