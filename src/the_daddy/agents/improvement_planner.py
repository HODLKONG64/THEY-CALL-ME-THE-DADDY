from __future__ import annotations

from typing import List

from ..models import (
    ArchitecturePlan,
    PlannedWorkItem,
    SelfEvolutionAction,
)


class ImprovementPlanner:
    """
    This is the decision layer.

    It decides:
    - what gets executed NOW
    - what gets queued
    - what gets escalated to architecture
    """

    # =========================
    # SELF EVOLUTION
    # =========================

    def plan_self_evolution(self, actions: List[SelfEvolutionAction]) -> List[SelfEvolutionAction]:
        """
        Keep only safe + bounded actions for immediate execution
        """
        safe = []

        for action in actions:
            if action.risk == "safe" and action.patches:
                safe.append(action)

        return safe[:3]  # hard cap

    # =========================
    # BUILD THREAD CONTROL
    # =========================

    def select_build_work(self, planned_work: List[PlannedWorkItem]) -> PlannedWorkItem | None:
        """
        Select ONE build thread per cycle
        """
        if not planned_work:
            return None

        candidates = [w for w in planned_work if w.state in ("proposed", "active")]

        if not candidates:
            return None

        # priority first, then oldest
        candidates.sort(key=lambda x: (x.priority, x.created_at))

        return candidates[0]

    # =========================
    # ARCHITECTURE ESCALATION
    # =========================

    def should_trigger_architecture(self, memory) -> bool:
        """
        Decide if we should escalate to architecture lane
        """

        failure_patterns = memory.ranked_failure_patterns()

        if not failure_patterns:
            return False

        top = failure_patterns[0]

        # repeated failure trigger
        if top.failure_count >= 3:
            return True

        return False

    def select_architecture_plan(self, plans: List[ArchitecturePlan]) -> ArchitecturePlan | None:
        """
        Pick first valid architecture plan
        """
        if not plans:
            return None

        for plan in plans:
            if plan.status == "proposed":
                return plan

        return None

    # =========================
    # MODE DECISION
    # =========================

    def decide_mode(self, memory, review) -> str:
        """
        FINAL MODE SWITCH

        Only ONE mode per run:
        - repair
        - build
        - architecture
        """

        # 1. architecture trigger (highest priority)
        if self.should_trigger_architecture(memory):
            if review.architecture_plans:
                return "architecture"

        # 2. continue build thread
        if memory.get_active_work():
            return "build"

        if review.build_actions:
            return "build"

        # 3. default fallback
        return "repair"