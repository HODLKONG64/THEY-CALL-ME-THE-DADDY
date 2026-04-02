from __future__ import annotations

from typing import List

from ..models import (
    ArchitecturePlan,
    PlannedWorkItem,
    SelfEvolutionAction,
)


class ImprovementPlanner:
    """
    FINAL PLANNER (AGGRESSIVE MODE)

    This version forces:
    - architecture mode when real patches exist
    - no more passive build-only loops
    """

    # =========================
    # SELF EVOLUTION
    # =========================

    def plan_self_evolution(self, actions: List[SelfEvolutionAction]) -> List[SelfEvolutionAction]:
        safe = []

        for action in actions:
            if action.risk == "safe" and action.patches:
                safe.append(action)

        return safe[:5]  # slightly more aggressive

    # =========================
    # BUILD THREAD CONTROL
    # =========================

    def select_build_work(self, planned_work: List[PlannedWorkItem]) -> PlannedWorkItem | None:
        if not planned_work:
            return None

        candidates = [w for w in planned_work if w.state in ("proposed", "active")]

        if not candidates:
            return None

        candidates.sort(key=lambda x: (x.priority, x.created_at))

        return candidates[0]

    # =========================
    # ARCHITECTURE ESCALATION
    # =========================

    def should_trigger_architecture(self, memory) -> bool:
        failure_patterns = memory.ranked_failure_patterns()

        if not failure_patterns:
            return False

        top = failure_patterns[0]

        # still keep safety fallback
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

    # =========================
    # MODE DECISION (FINAL FIX)
    # =========================

    def decide_mode(self, memory, review) -> str:
        """
        FINAL MODE SWITCH

        🔥 THIS IS THE KEY CHANGE:
        FORCE architecture when real patch bundles exist
        """

        # 🚀 FORCE ARCHITECTURE WHEN PATCHES EXIST
        has_arch_patches = any(
            plan.patch_bundle for plan in review.architecture_plans
        )

        if has_arch_patches:
            return "architecture"

        # fallback logic (kept for stability)
        if memory.get_active_work():
            return "build"

        if review.build_actions:
            return "build"

        return "repair"