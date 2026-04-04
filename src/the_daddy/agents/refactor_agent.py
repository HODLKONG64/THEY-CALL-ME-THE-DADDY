from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RefactorHint:
    path: str
    reason: str


class RefactorAgent:
    """
    Level 6 spawned agent.
    Suggests bounded refactor targets without mutating protected core files directly.
    """

    def suggest(self) -> list[RefactorHint]:
        return [
            RefactorHint(
                path="src/the_daddy/agents/improvement_planner.py",
                reason="Planner pressure logic can be extended incrementally via append-only helpers.",
            ),
            RefactorHint(
                path="src/the_daddy/runtime/architecture_probe.py",
                reason="Architecture visibility can grow without widening operational risk.",
            ),
        ]
