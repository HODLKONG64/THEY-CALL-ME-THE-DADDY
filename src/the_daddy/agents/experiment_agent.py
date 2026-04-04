from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExperimentPlan:
    name: str
    target_path: str
    summary: str


class ExperimentAgent:
    """
    Level 6 spawned agent.
    Carries tiny bounded experiments instead of speculative rewrites.
    """

    def plan(self) -> list[ExperimentPlan]:
        return [
            ExperimentPlan(
                name="planner-pressure-audit",
                target_path="src/the_daddy/agents/improvement_planner.py",
                summary="Add a small planner-facing audit surface when pressure stays high.",
            )
        ]
