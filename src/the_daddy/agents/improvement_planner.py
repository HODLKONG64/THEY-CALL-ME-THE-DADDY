from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

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
                reasons=["Self-evolution disabled"],
            )

        raw_actions = getattr(review, "self_evolution_actions", []) or []
        if not isinstance(raw_actions, list):
            raw_actions = []

        safe_actions = [
            action
            for action in raw_actions
            if getattr(action, "risk", "") == "safe" and bool(getattr(action, "patches", []))
        ]

        if not safe_actions:
            return PlannedSelfEvolution(
                enabled=True,
                actions=[],
                reasons=["No valid safe actions found"],
            )

        if max_actions <= 0:
            return PlannedSelfEvolution(
                enabled=True,
                actions=[],
                reasons=[f"Capped self-evolution actions from {len(safe_actions)} to 0."],
            )

        reasons: list[str] = []
        if len(safe_actions) > max_actions:
            reasons.append(f"Capped self-evolution actions from {len(safe_actions)} to {max_actions}.")
            safe_actions = safe_actions[:max_actions]

        return PlannedSelfEvolution(
            enabled=True,
            actions=safe_actions,
            reasons=reasons,
        )

    def select_build_work(self, planned_work: Iterable[Any]) -> object | None:
        try:
            candidates = [
                item for item in planned_work
                if getattr(item, "state", "") in {"proposed", "active"}
            ]
        except TypeError:
            return None

        if not candidates:
            return None

        candidates.sort(
            key=lambda item: (
                getattr(item, "priority", 0),
                getattr(item, "created_at", "")
            )
        )
        return candidates[0]

    def should_trigger_architecture(self, memory: Any) -> bool:
        failure_patterns = getattr(memory, "failure_patterns", {})
        if not hasattr(failure_patterns, "values"):
            return False

        ranked = sorted(
            failure_patterns.values(),
            key=lambda item: (getattr(item, "failure_count", 0), getattr(item, "updated_at", "")),
            reverse=True,
        )
        if not ranked:
            return False

        return int(getattr(ranked[0], "failure_count", 0) or 0) >= 3

    def decide_mode(self, memory, review: ArchitectureReview) -> str:
        state: Any = memory.state if hasattr(memory, "state") else memory

        architecture_plans = getattr(review, "architecture_plans", None)
        if isinstance(architecture_plans, list) and architecture_plans:
            if self.should_trigger_architecture(state):
                return "architecture"

        self_evolution_actions = getattr(review, "self_evolution_actions", None)
        if isinstance(self_evolution_actions, list):
            if self_evolution_actions:
                return "build"
        elif self_evolution_actions:
            return "repair"

        planned_work = getattr(state, "planned_work", None)
        if isinstance(planned_work, list):
            if planned_work:
                return "build"
        elif isinstance(planned_work, str):
            return "build"

        return "repair"