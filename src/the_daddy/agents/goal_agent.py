from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GoalDirective:
    name: str
    target_path: str
    priority: int
    summary: str


class GoalAgent:
    """
    Goal system.
    Turns sustained pressure into explicit build goals so the system stops
    waiting for obvious patches and starts driving a bounded roadmap.
    """

    def propose(self) -> list[GoalDirective]:
        return [
            GoalDirective(
                name="break-helper-dependence",
                target_path="src/the_daddy/agents/improvement_planner.py",
                priority=1,
                summary="Prioritize planner-facing work over helper churn under sustained pressure.",
            ),
            GoalDirective(
                name="spawn-next-safe-capability",
                target_path="src/the_daddy/agents/strategy_agent.py",
                priority=1,
                summary="Create or extend bounded capability agents before default maintenance work.",
            ),
            GoalDirective(
                name="strengthen-architecture-audit",
                target_path="src/the_daddy/runtime/architecture_probe.py",
                priority=2,
                summary="Improve architecture traceability only when it supports real planner action.",
            ),
        ]
