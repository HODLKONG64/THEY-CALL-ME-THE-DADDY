from __future__ import annotations

import hashlib
from typing import Any

from pydantic import ValidationError

from ..models import (
    AgentReputation,
    ArchitecturePlan,
    ArchitectureReview,
    FailurePatternRecord,
    MemoryState,
    MetricsLedgerEntry,
    PatchProvenance,
    PlannedWorkItem,
    RunRecord,
    VettingDecision,
    utc_now_iso,
)

# Legacy compat for older tests/imports
MEMORY_SCHEMA_VERSION = "3.0"
DaddyMemoryState = MemoryState


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


class MemoryRepository:
    def __init__(self, store: Any | None = None) -> None:
        self.store = store
        self._state = self._load_from_store()

    @property
    def state(self) -> MemoryState:
        return self._state

    def fingerprint(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

    def load(self) -> MemoryState:
        self._state = self._load_from_store()
        return self._state

    def save(self) -> MemoryState:
        self._state.last_saved_at = utc_now_iso()
        self._save_to_store(self._state)
        return self._state

    def snapshot(self) -> dict[str, Any]:
        return self._state.model_dump(mode="json")

    def latest_review(self) -> ArchitectureReview | None:
        if not self._state.architecture_reviews:
            return None
        return self._state.architecture_reviews[-1]

    def add_architecture_review(self, review: ArchitectureReview) -> ArchitectureReview:
        self._state.architecture_reviews.append(review)
        self.save()
        return review

    def add_planned_work(self, item: PlannedWorkItem) -> PlannedWorkItem:
        self._state.planned_work.append(item)
        self.save()
        return item

    def add_architecture_plan(self, plan: ArchitecturePlan) -> ArchitecturePlan:
        self._state.architecture_queue.append(plan)
        self.save()
        return plan

    def get_pending_architecture(self) -> list[ArchitecturePlan]:
        return [p for p in self._state.architecture_queue if p.status in {"proposed", "active"}]

    def get_active_work(self) -> list[PlannedWorkItem]:
        return [w for w in self._state.planned_work if w.state in {"proposed", "active"}]

    def ranked_failure_patterns(self) -> list[FailurePatternRecord]:
        return sorted(
            self._state.failure_patterns.values(),
            key=lambda item: (item.failure_count, item.updated_at),
            reverse=True,
        )

    def record_patch(
        self,
        run_id: str,
        mode: str,
        path: str,
        description: str,
        route: str,
        source: str = "reviewer",
        patch_fingerprint: str = "",
    ) -> PatchProvenance:
        entry = PatchProvenance(
            run_id=run_id,
            mode=mode,
            path=path,
            description=description,
            patch_fingerprint=patch_fingerprint,
            route=route,
            source=source,
        )
        self._state.patch_provenance.append(entry)
        self.save()
        return entry

    def record_failure_pattern(
        self,
        signature: str,
        details: dict[str, Any] | None = None,
        success: bool = False,
    ) -> FailurePatternRecord:
        if not signature:
            raise ValueError("signature is required")

        existing = self._state.failure_patterns.get(signature)
        if existing is None:
            existing = FailurePatternRecord(signature=signature)

        payload = dict(details or {})
        existing.success_count += 1 if success else 0
        existing.failure_count += 0 if success else 1
        existing.updated_at = utc_now_iso()

        if "route" in payload:
            existing.last_route = str(payload["route"])
        if "diagnosis" in payload:
            existing.last_summary = str(payload["diagnosis"])
        if "summary" in payload:
            existing.last_summary = str(payload["summary"])

        related_files = payload.get("related_files") or []
        if isinstance(related_files, list):
            existing.related_files = _dedupe_keep_order(existing.related_files + [str(x) for x in related_files])

        self._state.failure_patterns[signature] = existing
        self.save()
        return existing

    def record_metrics(self, entry: MetricsLedgerEntry) -> MetricsLedgerEntry:
        self._state.metrics_ledger.append(entry)
        self.save()
        return entry

    def add_run(self, record: RunRecord) -> RunRecord:
        self._state.runs.append(record)
        self.save()
        return record

    def add_backlog_items(self, items: list[str]) -> list[str]:
        self._state.backlog = _dedupe_keep_order(self._state.backlog + [str(item) for item in items])
        self.save()
        return self._state.backlog

    def update_reputation(
        self,
        actor: str,
        decision: VettingDecision | None = None,
        **fields: Any,
    ) -> AgentReputation:
        existing = self._state.reputations.get(actor)
        rep = existing or AgentReputation(agent_id=actor)

        delta = 0
        if decision is not None:
            delta = int(getattr(decision, "reputation_delta", 0))
            if getattr(decision, "accepted", False):
                rep.accepted_count += 1
            elif getattr(decision, "route", "") == "branch":
                rep.staged_count += 1
            else:
                rep.rejected_count += 1

        rep.trust_score = max(0, min(100, rep.trust_score + delta))

        for key, value in fields.items():
            if hasattr(rep, key):
                setattr(rep, key, value)

        rep.updated_at = utc_now_iso()
        self._state.reputations[actor] = rep
        self.save()
        return rep

    def _load_from_store(self) -> MemoryState:
        raw: Any = {}
        if self.store is None:
            return MemoryState()

        if hasattr(self.store, "load"):
            raw = self.store.load()
        elif hasattr(self.store, "get"):
            raw = self.store.get()
        elif hasattr(self.store, "read"):
            raw = self.store.read()

        return self._coerce_state(raw)

    def _save_to_store(self, state: MemoryState) -> None:
        if self.store is None:
            return
        payload = state.model_dump(mode="json")
        if hasattr(self.store, "save"):
            self.store.save(payload)
        elif hasattr(self.store, "put"):
            self.store.put(payload)
        elif hasattr(self.store, "write"):
            self.store.write(payload)

    def _coerce_state(self, raw: Any) -> MemoryState:
        if isinstance(raw, MemoryState):
            return raw

        if not isinstance(raw, dict):
            return MemoryState()

        raw = dict(raw)

        failure_patterns = raw.get("failure_patterns", {})
        if isinstance(failure_patterns, dict):
            repaired_patterns: dict[str, Any] = {}
            for signature, value in failure_patterns.items():
                if isinstance(value, dict):
                    item = dict(value)
                    item.setdefault("signature", signature)
                    repaired_patterns[signature] = item
                else:
                    repaired_patterns[signature] = {"signature": signature}
            raw["failure_patterns"] = repaired_patterns

        reputations = raw.get("reputations", {})
        if isinstance(reputations, dict):
            repaired_reputations: dict[str, Any] = {}
            for actor, value in reputations.items():
                if isinstance(value, dict):
                    item = dict(value)
                    item.setdefault("agent_id", actor)
                    repaired_reputations[actor] = item
                else:
                    repaired_reputations[actor] = {"agent_id": actor}
            raw["reputations"] = repaired_reputations

        try:
            state = MemoryState.model_validate(raw)
        except ValidationError:
            state = MemoryState()

            for item in raw.get("architecture_reviews", []) or []:
                try:
                    state.architecture_reviews.append(ArchitectureReview.model_validate(item))
                except ValidationError:
                    continue

            for item in raw.get("runs", []) or []:
                try:
                    state.runs.append(RunRecord.model_validate(item))
                except ValidationError:
                    continue

            for item in raw.get("planned_work", []) or []:
                try:
                    state.planned_work.append(PlannedWorkItem.model_validate(item))
                except ValidationError:
                    continue

            for item in raw.get("architecture_queue", []) or []:
                try:
                    state.architecture_queue.append(ArchitecturePlan.model_validate(item))
                except ValidationError:
                    continue

            for signature, item in (raw.get("failure_patterns", {}) or {}).items():
                try:
                    parsed = FailurePatternRecord.model_validate(item)
                    state.failure_patterns[signature] = parsed
                except ValidationError:
                    try:
                        state.failure_patterns[signature] = FailurePatternRecord(signature=signature)
                    except ValidationError:
                        continue

            for actor, item in (raw.get("reputations", {}) or {}).items():
                try:
                    state.reputations[actor] = AgentReputation.model_validate(item)
                except ValidationError:
                    state.reputations[actor] = AgentReputation(agent_id=actor)

            for item in raw.get("metrics_ledger", []) or []:
                try:
                    state.metrics_ledger.append(MetricsLedgerEntry.model_validate(item))
                except ValidationError:
                    continue

            for item in raw.get("patch_provenance", []) or []:
                try:
                    state.patch_provenance.append(PatchProvenance.model_validate(item))
                except ValidationError:
                    continue

            backlog = raw.get("backlog", []) or []
            if isinstance(backlog, list):
                state.backlog = [str(x) for x in backlog]

            improvement_history = raw.get("improvement_history", []) or []
            if isinstance(improvement_history, list):
                state.improvement_history = improvement_history

            quarantine_events = raw.get("quarantine_events", []) or []
            if isinstance(quarantine_events, list):
                state.quarantine_events = quarantine_events

        if not state.schema_version:
            state.schema_version = "3.0"
        state.last_saved_at = utc_now_iso()
        return state