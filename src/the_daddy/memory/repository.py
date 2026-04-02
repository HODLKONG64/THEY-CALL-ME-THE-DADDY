from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, Field

from ..models import ArchitectureReview, ReputationRecord, RunRecord, VetDecision


MEMORY_SCHEMA_VERSION = 2


class DaddyMemoryState(BaseModel):
    schema_version: int = MEMORY_SCHEMA_VERSION
    runs: list[dict[str, Any]] = Field(default_factory=list)
    architecture_reviews: list[dict[str, Any]] = Field(default_factory=list)
    improvement_backlog: list[str] = Field(default_factory=list)
    improvement_history: list[dict[str, Any]] = Field(default_factory=list)
    failure_patterns: dict[str, dict[str, Any]] = Field(default_factory=dict)
    quarantine_events: list[dict[str, Any]] = Field(default_factory=list)
    reputations: dict[str, dict[str, Any]] = Field(default_factory=dict)
    metrics_ledger: list[dict[str, Any]] = Field(default_factory=list)


class MemoryRepository:
    def __init__(self, store) -> None:
        self.store = store
        raw = store.load_memory()
        if raw and raw.get("schema_version") in (None, MEMORY_SCHEMA_VERSION):
            if "schema_version" not in raw:
                raw["schema_version"] = MEMORY_SCHEMA_VERSION
            self.state = DaddyMemoryState.model_validate(raw)
        else:
            self.state = DaddyMemoryState()

    def save(self) -> None:
        self.store.save_memory(self.state.model_dump(mode="json"))

    def latest_review(self) -> ArchitectureReview | None:
        if not self.state.architecture_reviews:
            return None
        return ArchitectureReview.model_validate(self.state.architecture_reviews[-1])

    def add_architecture_review(self, review: ArchitectureReview) -> None:
        self.state.architecture_reviews.append(review.model_dump(mode="json"))
        self.state.architecture_reviews = self.state.architecture_reviews[-50:]

    def add_run(self, record: RunRecord) -> None:
        self.state.runs.append(record.model_dump(mode="json"))
        self.state.runs = self.state.runs[-100:]
        self.record_metrics(
            {
                "run_id": record.run_id,
                "success": record.success,
                "attempt_count": record.attempt_count,
                "self_evolution_route": record.self_evolution.route if record.self_evolution else "none",
                "self_evolution_applied": record.self_evolution.applied if record.self_evolution else False,
                "patch_count": len(record.patches_applied),
            }
        )
        self.save()

    def record_metrics(self, item: dict[str, Any]) -> None:
        self.state.metrics_ledger.append(item)
        self.state.metrics_ledger = self.state.metrics_ledger[-300:]

    def record_improvement_result(self, title: str, applied: bool, payload: dict[str, Any]) -> None:
        self.state.improvement_history.append({"title": title, "applied": applied, **payload})
        self.state.improvement_history = self.state.improvement_history[-100:]

    def record_failure_pattern(self, signature: str, payload: dict[str, Any], success: bool) -> None:
        current = self.state.failure_patterns.get(signature, {"count": 0, "success_count": 0, "events": []})
        current["count"] += 1
        if success:
            current["success_count"] += 1
        current["events"].append(payload)
        current["events"] = current["events"][-20:]
        self.state.failure_patterns[signature] = current
        self.save()

    def fingerprint(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

    def add_quarantine_event(self, event: dict[str, Any]) -> None:
        self.state.quarantine_events.append(event)
        self.state.quarantine_events = self.state.quarantine_events[-100:]
        self.save()

    def update_reputation(self, agent_id: str, decision: VetDecision) -> ReputationRecord:
        current = ReputationRecord.model_validate(self.state.reputations.get(agent_id, {"agent_id": agent_id}))
        current.total += 1
        current.score += decision.reputation_delta
        if decision.accepted:
            current.accepted += 1
        else:
            current.rejected += 1
        self.state.reputations[agent_id] = current.model_dump(mode="json")
        self.save()
        return current
