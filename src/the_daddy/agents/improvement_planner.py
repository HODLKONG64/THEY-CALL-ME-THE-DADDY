from __future__ import annotations

from typing import List

from ..models import (
    ArchitecturePlan,
    PlannedWorkItem,
    SelfEvolutionAction,
)


class ImprovementPlanner:
    def plan_self_evolution(self, actions: List[SelfEvolutionAction]) -> List[SelfEvolutionAction]:
        safe = []
        for action in actions:
            if action.risk == "safe" and action.patches:
                safe.append(action)
        return safe[:3]

    def select_build_work(self, planned_work: List[PlannedWorkItem]) -> PlannedWorkItem | None:
        if not planned_work:
            return None
        candidates = [w for w in planned_work if w.state in ("proposed", "active")]
        if not candidates:
            return None
        candidates.sort(key=lambda x: (x.priority, x.created_at))
        return candidates[0]

    def should_trigger_architecture(self, memory) -> bool:
        failure_patterns = memory.ranked_failure_patterns()
        if not failure_patterns:
            return False
        top = failure_patterns[0]
        if top.failure_count >= 3:
            return True
        return False

    def select_architecture_plan(self, plans: List[ArchitecturePlan]) -> ArchitecturePlan | None:
        if not plans:
            return None
        for plan in plans:
            if plan.status == "proposed":
                return plan
        return None

    def decide_mode(self, memory, review) -> str:
        if self.should_trigger_architecture(memory):
            if review.architecture_plans:
                return "architecture"
        if memory.get_active_work():
            return "build"
        if review.build_actions:
            return "build"
        return "repair"
