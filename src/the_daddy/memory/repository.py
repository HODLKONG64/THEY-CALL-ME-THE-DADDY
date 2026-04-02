from __future__ import annotations

from typing import Any, Dict
import hashlib

from ..models import (
    ArchitectureReview,
    RunRecord,
    MemoryState,
    AgentReputation,
    VettingDecision,
    FailurePatternRecord,
    PlannedWorkItem,
    ArchitecturePlan,
    PatchProvenance,
    MetricsLedgerEntry,
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

    def fingerprint(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

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

    # --- failure patterns (with weighting) ---

    def record_failure_pattern(self, key: str, data: Dict[str, Any], success: bool) -> None:
        existing = self.state.failure_patterns.get(key)

        if not existing:
            existing = FailurePatternRecord(signature=key)

        if success:
            existing.success_count += 1
        else:
            existing.failure_count += 1

        existing.last_summary = data.get("diagnosis", "")
        existing.last_route = data.get("route", "")
        existing.related_files = data.get("files", [])
        existing.updated_at = self._now()

        self.state.failure_patterns[key] = existing

    # --- improvement history ---

    def record_improvement_result(self, title: str, applied: bool, payload: Dict[str, Any]) -> None:
        self.state.improvement_history.append({
            "title": title,
            "applied": applied,
            "payload": payload,
            "timestamp": self._now(),
        })

    # --- planned work (multi-cycle builds) ---

    def add_planned_work(self, item: PlannedWorkItem) -> None:
        self.state.planned_work.append(item)

    def get_active_work(self) -> list[PlannedWorkItem]:
        return [w for w in self.state.planned_work if w.state == "active"]

    def update_work_state(self, work_id: str, state: str) -> None:
        for w in self.state.planned_work:
            if w.work_id == work_id:
                w.state = state
                w.updated_at = self._now()

    # --- architecture queue ---

    def add_architecture_plan(self, plan: ArchitecturePlan) -> None:
        self.state.architecture_queue.append(plan)

    def get_pending_architecture(self) -> list[ArchitecturePlan]:
        return [p for p in self.state.architecture_queue if p.status == "proposed"]

    def update_architecture_status(self, title: str, status: str) -> None:
        for p in self.state.architecture_queue:
            if p.title == title:
                p.status = status
                p.updated_at = self._now()

    # --- patch provenance ---

    def record_patch(self, run_id: str, mode: str, path: str, description: str, route: str):
        self.state.patch_provenance.append(
            PatchProvenance(
                run_id=run_id,
                mode=mode,
                path=path,
                description=description,
                route=route,
            )
        )

    # --- metrics ledger ---

    def record_metrics(self, entry: MetricsLedgerEntry) -> None:
        self.state.metrics_ledger.append(entry)

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
