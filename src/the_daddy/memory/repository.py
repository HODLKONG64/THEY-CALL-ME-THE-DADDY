from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from ..models import (
    ArchitecturePlan,
    ArchitectureReview,
    FailurePatternRecord,
    MemoryState,
    MetricsLedgerEntry,
    PatchProvenance,
    PlannedWorkItem,
    RunRecord,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryRepository:
    def __init__(self, store) -> None:
        self.store = store
        self.state: MemoryState = self._load()

    def _load(self) -> MemoryState:
        data = self.store.load()
        if not data:
            return MemoryState()
        return MemoryState.model_validate(data)

    def save(self) -> None:
        self.state.last_saved_at = _now()
        self.store.save(self.state.model_dump(mode="json"))

    # -------------------------
    # Core helpers
    # -------------------------

    def fingerprint(self, text: str) -> str:
        if not text:
            return "empty"
        return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

    # -------------------------
    # Reviews
    # -------------------------

    def add_architecture_review(self, review: ArchitectureReview) -> None:
        self.state.architecture_reviews.append(review)
        self._trim_reviews()

    def latest_review(self) -> ArchitectureReview | None:
        if not self.state.architecture_reviews:
            return None
        return self.state.architecture_reviews[-1]

    def _trim_reviews(self, keep: int = 40) -> None:
        if len(self.state.architecture_reviews) > keep:
            self.state.architecture_reviews = self.state.architecture_reviews[-keep:]

    # -------------------------
    # Runs
    # -------------------------

    def add_run(self, run: RunRecord) -> None:
        self.state.runs.append(run)
        self._trim_runs()

    def _trim_runs(self, keep: int = 100) -> None:
        if len(self.state.runs) > keep:
            self.state.runs = self.state.runs[-keep:]

    # -------------------------
    # Backlog
    # -------------------------

    def add_backlog_items(self, items: list[str]) -> None:
        for item in items:
            if item and item not in self.state.backlog:
                self.state.backlog.append(item)

    # -------------------------
    # Failure learning
    # -------------------------

    def record_failure_pattern(self, signature: str, context: dict[str, Any], resolved: bool) -> None:
        existing = self.state.failure_patterns.get(signature)
        if not existing:
            existing = FailurePatternRecord(signature=signature)

        if resolved:
            existing.success_count += 1
        else:
            existing.failure_count += 1

        existing.last_route = str(context.get("route", ""))
        existing.last_summary = str(context.get("diagnosis", ""))
        existing.related_files = list(context.get("files", [])) if isinstance(context.get("files", []), list) else []
        existing.updated_at = _now()

        self.state.failure_patterns[signature] = existing

    def ranked_failure_patterns(self) -> list[FailurePatternRecord]:
        weights = self.state.learning_weights
        ranked = list(self.state.failure_patterns.values())

        def score(item: FailurePatternRecord) -> float:
            return (
                item.failure_count * weights.repeated_failure_weight
                + item.success_count * weights.repeated_success_weight
            )

        return sorted(ranked, key=score, reverse=True)

    # -------------------------
    # Improvement history
    # -------------------------

    def record_improvement_result(self, title: str, applied: bool, payload: dict[str, Any]) -> None:
        self.state.improvement_history.append(
            {
                "title": title,
                "applied": applied,
                "payload": payload,
                "timestamp": _now(),
            }
        )
        if len(self.state.improvement_history) > 150:
            self.state.improvement_history = self.state.improvement_history[-150:]

    # -------------------------
    # Planned work / multi-cycle build
    # -------------------------

    def add_planned_work(self, item: PlannedWorkItem) -> None:
        if not any(existing.work_id == item.work_id for existing in self.state.planned_work):
            self.state.planned_work.append(item)

    def get_active_work(self) -> list[PlannedWorkItem]:
        return [w for w in self.state.planned_work if w.state == "active"]

    def get_next_build_work(self) -> PlannedWorkItem | None:
        candidates = [w for w in self.state.planned_work if w.state in {"proposed", "active"}]
        if not candidates:
            return None
        candidates.sort(key=lambda x: (x.priority, x.created_at))
        return candidates[0]

    def update_work_state(self, work_id: str, state: str, note: str | None = None) -> None:
        for work in self.state.planned_work:
            if work.work_id == work_id:
                work.state = state
                work.updated_at = _now()
                if note:
                    work.notes.append(note)

    # -------------------------
    # Architecture queue
    # -------------------------

    def add_architecture_plan(self, plan: ArchitecturePlan) -> None:
        if not any(existing.title == plan.title for existing in self.state.architecture_queue):
            self.state.architecture_queue.append(plan)

    def get_pending_architecture(self) -> list[ArchitecturePlan]:
        return [p for p in self.state.architecture_queue if p.status == "proposed"]

    def update_architecture_status(self, title: str, status: str) -> None:
        for plan in self.state.architecture_queue:
            if plan.title == title:
                plan.status = status
                plan.updated_at = _now()

    # -------------------------
    # Patch provenance
    # -------------------------

    def record_patch(self, run_id: str, mode: str, path: str, description: str, route: str, source: str = "reviewer") -> None:
        self.state.patch_provenance.append(
            PatchProvenance(
                run_id=run_id,
                mode=mode,
                path=path,
                description=description,
                source=source,
                route=route,
            )
        )
        if len(self.state.patch_provenance) > 300:
            self.state.patch_provenance = self.state.patch_provenance[-300:]

    # -------------------------
    # Metrics
    # -------------------------

    def record_metrics(self, entry: MetricsLedgerEntry) -> None:
        self.state.metrics_ledger.append(entry)
        if len(self.state.metrics_ledger) > 300:
            self.state.metrics_ledger = self.state.metrics_ledger[-300:]

    # -------------------------
    # External proposals / reputation
    # -------------------------

    def add_quarantine_event(self, event: dict[str, Any]) -> None:
        self.state.quarantine_events.append(event)
        if len(self.state.quarantine_events) > 200:
            self.state.quarantine_events = self.state.quarantine_events[-200:]
