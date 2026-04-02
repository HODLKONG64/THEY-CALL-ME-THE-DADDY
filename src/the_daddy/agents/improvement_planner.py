from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from pydantic import ValidationError

from ..models import ArchitectureReview, MemoryState, PatchAction, SelfEvolutionAction


@dataclass
class PlannedSelfEvolution:
    enabled: bool
    actions: list[SelfEvolutionAction] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


class ImprovementPlanner:
    def _safe_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, (str, bytes, dict)):
            return []
        try:
            return list(value)
        except TypeError:
            return []

    def _coerce_patch_action(self, value: Any) -> PatchAction | None:
        if isinstance(value, PatchAction):
            return value
        if isinstance(value, dict):
            try:
                return PatchAction.model_validate(value)
            except ValidationError:
                return None
        return None

    def _normalize_patches(self, value: Any) -> list[PatchAction]:
        normalized: list[PatchAction] = []
        for item in self._safe_list(value):
            patch = self._coerce_patch_action(item)
            if not patch:
                continue
            if not getattr(patch, "path", ""):
                continue
            if getattr(patch, "operation", None) not in {"replace_file", "regex_replace"}:
                continue
            normalized.append(patch)
        return normalized

    def _coerce_self_evolution_action(self, value: Any) -> SelfEvolutionAction | None:
        if isinstance(value, SelfEvolutionAction):
            patches = self._normalize_patches(getattr(value, "patches", None))
            if not patches:
                return None
            return value.model_copy(update={"patches": patches})

        if isinstance(value, dict):
            normalized_payload = {
                "title": value.get("title"),
                "description": value.get("description"),
                "risk": value.get("risk"),
                "patches": [patch.model_dump() for patch in self._normalize_patches(value.get("patches"))],
            }
            try:
                action = SelfEvolutionAction.model_validate(normalized_payload)
            except ValidationError:
                return None
            patches = self._normalize_patches(getattr(action, "patches", None))
            if not patches:
                return None
            return action.model_copy(update={"patches": patches})
        return None

    def _normalize_self_evolution_actions(self, value: Any) -> list[SelfEvolutionAction]:
        normalized: list[SelfEvolutionAction] = []
        for item in self._safe_list(value):
            action = self._coerce_self_evolution_action(item)
            if not action:
                continue
            if not isinstance(getattr(action, "title", None), str) or not action.title:
                continue
            if not isinstance(getattr(action, "description", None), str) or not action.description:
                continue
            if getattr(action, "risk", None) != "safe":
                continue
            patches = self._normalize_patches(getattr(action, "patches", None))
            if not patches:
                continue
            normalized.append(action.model_copy(update={"patches": patches}))
        return normalized

    def merge_review_into_backlog(self, memory: MemoryState, review: ArchitectureReview) -> list[str]:
        additions: list[str] = []

        recommendations = self._safe_list(getattr(review, "recommendations", None))
        backlog_items = self._safe_list(getattr(review, "backlog_items", None))

        for item in recommendations + backlog_items:
            if isinstance(item, str) and item and item not in memory.backlog:
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

        safe_actions = self._normalize_self_evolution_actions(getattr(review, "self_evolution_actions", None))

        if not safe_actions:
            return PlannedSelfEvolution(
                enabled=True,
                actions=[],
                reasons=["No valid safe actions found"],
            )

        if len(safe_actions) > max_actions:
            safe_actions = safe_actions[:max_actions]

        return PlannedSelfEvolution(
            enabled=True,
            actions=safe_actions,
            reasons=[],
        )

    def select_build_work(self, planned_work: Iterable) -> object | None:
        candidates = [
            item for item in self._safe_list(planned_work)
            if getattr(item, "state", "") in {"proposed", "active"}
        ]
        if not candidates:
            return None

        candidates.sort(
            key=lambda item: (
                getattr(item, "priority", 0),
                getattr(item, "created_at", "")
            )
        )
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

        architecture_plans = self._safe_list(getattr(review, "architecture_plans", None))
        self_evolution_actions = self._normalize_self_evolution_actions(getattr(review, "self_evolution_actions", None))
        planned_work = self._safe_list(getattr(state, "planned_work", None))

        if architecture_plans and self.should_trigger_architecture(state):
            return "architecture"
        if self_evolution_actions:
            return "self_evolution"
        if self.select_build_work(planned_work):
            return "build"
        return "none"
