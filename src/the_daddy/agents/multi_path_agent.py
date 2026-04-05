from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EvolutionPath:
    name: str
    target_path: str
    priority: int
    summary: str


class MultiPathAgent:
    """
    Level 9 multi-path evolution agent.
    Produces multiple bounded evolution paths so the system can choose
    the next safe capability instead of stalling on a single chain.
    """

    def propose(self) -> list[EvolutionPath]:
        return [
            EvolutionPath(
                name="extend-goal-agent",
                target_path="src/the_daddy/agents/goal_agent.py",
                priority=1,
                summary="Extend goal routing when pressure stays high and default maintenance is blocked.",
            ),
            EvolutionPath(
                name="extend-self-rewrite-agent",
                target_path="src/the_daddy/agents/self_rewrite_agent.py",
                priority=2,
                summary="Add another bounded rewrite-planning surface instead of falling back to helper churn.",
            ),
            EvolutionPath(
                name="extend-strategy-agent",
                target_path="src/the_daddy/agents/strategy_agent.py",
                priority=3,
                summary="Expand planner-facing strategy signals when the system remains healthy but stagnant.",
            ),
        ]
