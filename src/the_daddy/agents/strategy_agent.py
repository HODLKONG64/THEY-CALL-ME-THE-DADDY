from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class StrategySignal:
    title: str
    description: str
    priority: int = 1


class StrategyAgent:
    """
    Level 6 spawned agent.
    Produces bounded strategy signals when the system is healthy but stagnant.
    """

    def propose(self, memory_summary: dict[str, Any] | None = None) -> list[StrategySignal]:
        summary = memory_summary or {}
        pressure_score = int(summary.get("pressure_score", 0) or 0)
        patch_drought = int(summary.get("runs_without_patches", 0) or 0)

        signals: list[StrategySignal] = []
        if pressure_score >= 5:
            signals.append(
                StrategySignal(
                    title="Escalate bounded planner work",
                    description="Pressure remains high; prefer planner-facing changes over helper churn.",
                    priority=1,
                )
            )
        if patch_drought >= 5:
            signals.append(
                StrategySignal(
                    title="Break patch drought",
                    description="Patch output has stalled; prioritize one bounded source-level move.",
                    priority=1,
                )
            )
        return signals
