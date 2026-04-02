from __future__ import annotations

from typing import Any, Dict

from ..models import (
    ArchitectureReview,
    RunRecord,
    MemoryState,
    AgentReputation,
    VettingDecision,
)


class MemoryRepository:
    def __init__(self, store):
        self.store = store
        self.state: MemoryState = self._load()

    def _load(self) -> MemoryState:
        data = self.store.load()
        if not data:
            return MemoryState()
        return MemoryState.model_validate(data)

    def save(self) -> None:
        self.state.last_saved_at = self._now()
        self.store.save(self.state.model_dump(mode="json"))

    def _now(self) -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()

    # --- architecture reviews ---

    def add_architecture_review(self, review: ArchitectureReview) -> None:
        self.state.architecture_reviews.append(review)

    def latest_review(self) -> ArchitectureReview | None:
        if not self.state.architecture_reviews:
            return None
        return self.state.architecture_reviews[-1]

    # --- runs ---

    def add_run(self, run: RunRecord) -> None:
        self.state.runs.append(run)

    # --- backlog ---

    def add_backlog_items(self, items: list[str]) -> None:
        for item in items:
            if item not in self.state.backlog:
                self.state.backlog.append(item)

    # --- failure patterns ---

    def record_failure_pattern(self, key: str, data: Dict[str, Any], success: bool) -> None:
        self.state.failure_patterns[key] = {
            "data": data,
            "success": success,
            "updated_at": self._now(),
        }

    # --- improvement history ---

    def record_improvement_result(self, title: str, applied: bool, payload: Dict[str, Any]) -> None:
        self.state.improvement_history.append({
            "title": title,
            "applied": applied,
            "payload": payload,
            "timestamp": self._now(),
        })

    # --- quarantine ---

    def add_quarantine_event(self, event: Dict[str, Any]) -> None:
        self.state.quarantine_events.append(event)

    # --- reputation ---

    def update_reputation(self, agent_id: str, decision: VettingDecision) -> AgentReputation:
        rep = self.state.reputations.get(agent_id)

        if not rep:
            rep = AgentReputation(agent_id=agent_id)

        if decision.accepted:
            rep.accepted += 1
            rep.score += max(decision.reputation_delta, 1)
        else:
            rep.rejected += 1
            rep.score += decision.reputation_delta

        rep.updated_at = self._now()
        self.state.reputations[agent_id] = rep
        return rep
