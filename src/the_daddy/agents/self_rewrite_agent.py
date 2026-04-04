from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SelfRewritePlan:
    target_path: str
    summary: str
    mode: str = "append_only"


class SelfRewriteAgent:
    """
    Level 7 spawned agent.
    Produces bounded self-rewrite plans for protected files without allowing destructive rewrites.
    """

    def plan(self) -> list[SelfRewritePlan]:
        return [
            SelfRewritePlan(
                target_path="src/the_daddy/agents/improvement_planner.py",
                summary="Append a new planner-facing decision surface instead of mutating existing planner behavior destructively.",
            ),
            SelfRewritePlan(
                target_path="src/the_daddy/agents/reviewer.py",
                summary="Extend reviewer routing with one new bounded decision gate instead of replacing current safeguards.",
            ),
        ]
