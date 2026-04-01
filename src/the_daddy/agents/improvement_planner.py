from __future__ import annotations

from dataclasses import dataclass, field

from ..models import ArchitectureReview, MemoryState, PatchAction, SelfEvolutionExecution


@dataclass
class PlannedEvolution:
    actions: list[PatchAction] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


class ImprovementPlanner:
    def merge_review_into_backlog(self, memory: MemoryState, review: ArchitectureReview) -> list[str]:
        added: list[str] = []
        for item in [*review.backlog_items, *review.recommendations]:
            if item not in memory.backlog:
                memory.backlog.append(item)
                added.append(item)
        return added

    def plan_self_evolution(self, review: ArchitectureReview, *, enabled: bool, max_actions: int) -> PlannedEvolution:
        if not enabled:
            return PlannedEvolution(reasons=["Self-evolution disabled by settings."])
        if not review.self_evolution_actions:
            return PlannedEvolution(reasons=["Wake audit produced no self-evolution actions."])

        selected = review.self_evolution_actions[:max_actions]
        reasons = []
        if len(review.self_evolution_actions) > max_actions:
            reasons.append(f"Capped self-evolution actions to {max_actions} items.")
        reasons.extend(review.execution_notes)
        return PlannedEvolution(actions=selected, reasons=reasons)

    def build_execution_result(
        self,
        *,
        enabled: bool,
        attempted: bool,
        applied: bool,
        route: str,
        summary: str,
        reasons: list[str],
        proposed_count: int,
        applied_count: int,
        patches: list[dict],
    ) -> SelfEvolutionExecution:
        return SelfEvolutionExecution(
            enabled=enabled,
            attempted=attempted,
            applied=applied,
            route=route,
            summary=summary,
            reasons=reasons,
            proposed_count=proposed_count,
            applied_count=applied_count,
            patches=patches,
        )
