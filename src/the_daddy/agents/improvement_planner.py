from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from ..models import ArchitectureReview, MemoryState, SelfEvolutionAction


@dataclass
class PlannedSelfEvolution:
    enabled: bool
    actions: list[SelfEvolutionAction] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


class ImprovementPlanner:
    def merge_review_into_backlog(self, memory: MemoryState, review: ArchitectureReview) -> list[str]:
        additions: list[str] = []

        for item in list(review.recommendations) + list(review.backlog_items):
            if item and item not in memory.backlog:
                memory.backlog.append(item)
                additions.append(item)

        return additions

    def plan_self_evolution(
        self,
        review: ArchitectureReview,
        enabled: bool,
        max_actions: int,
    ) -> PlannedSelfEvolution:
        if not enabled:
            return PlannedSelfEvolution(
                enabled=False,
                actions=[],
                reasons=["Self-evolution disabled by configuration."],
            )

        safe_actions = [action for action in review.self_evolution_actions if action.risk == "safe" and action.patches]

        reasons: list[str] = []
        if len(safe_actions) > max_actions:
            reasons.append(f"Capped self-evolution actions from {len(safe_actions)} to {max_actions}.")

        if not safe_actions:
            reasons.append("No safe self-evolution actions available.")

        return PlannedSelfEvolution(
            enabled=True,
            actions=safe_actions[:max_actions],
            reasons=reasons,
        )

    def select_build_work(self, planned_work: Iterable) -> object | None:
        candidates = [item for item in planned_work if getattr(item, "state", "") in {"proposed", "active"}]
        if not candidates:
            return None
        candidates.sort(key=lambda item: (getattr(item, "priority", 0), getattr(item, "created_at", "")))
        return candidates[0]

    def should_trigger_architecture(self, memory: MemoryState) -> bool:
        ranked = sorted(
            memory.failure_patterns.values(),
            key=lambda item: (item.failure_count, item.updated_at),
            reverse=True,
        )
        if not ranked:
            return False
        return ranked[0].failure_count >= 3

    def decide_mode(self, memory, review: ArchitectureReview) -> str:
        state: MemoryState = memory.state if hasattr(memory, "state") else memory

        if review.architecture_plans and self.should_trigger_architecture(state):
            return "architecture"

        if review.self_evolution_actions:
            return "build"

        if state.planned_work:
            return "build"

        return "repair"
