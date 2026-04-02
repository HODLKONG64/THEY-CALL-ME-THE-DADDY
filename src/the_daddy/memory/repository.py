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


def _utc_now() -> str:
    return utc_now_iso()


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

    @state.setter
    def state(self, value: MemoryState) -> None:
        self._state = value

    def fingerprint(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

    # -------------------------------------------------------------------------
    # Public lifecycle methods
    # -------------------------------------------------------------------------

    def load(self) -> MemoryState:
        self._state = self._load_from_store()
        return self._state

    # Legacy compat for older callers
    def _load(self) -> MemoryState:
        return self.load()

    def save(self) -> MemoryState:
        self._state.last_saved_at = _utc_now()
        self._save_to_store(self._state)
        return self._state

    def snapshot(self) -> dict[str, Any]:
        return self._state.model_dump(mode="json")

    # -------------------------------------------------------------------------
    # Reviews / plans / work
    # -------------------------------------------------------------------------

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
        return [
            plan
            for plan in self._state.architecture_queue
            if getattr(plan, "status", "") in {"proposed", "active"}
        ]

    def get_active_work(self) -> list[PlannedWorkItem]:
        return [
            work
            for work in self._state.planned_work
            if getattr(work, "state", "") in {"proposed", "active"}
        ]

    # -------------------------------------------------------------------------
    # Failure patterns
    # -------------------------------------------------------------------------

    def ranked_failure_patterns(self) -> list[FailurePatternRecord]:
        return sorted(
            self._state.failure_patterns.values(),
            key=lambda item: (item.failure_count, item.updated_at),
            reverse=True,
        )

    def get_failure_hotspots(self) -> list[str]:
        return [item.signature for item in self.ranked_failure_patterns()[:5]]

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

        if success:
            existing.success_count += 1
        else:
            existing.failure_count += 1

        existing.updated_at = _utc_now()

        route = payload.get("route")
        if route is not None:
            existing.last_route = str(route)

        diagnosis = payload.get("diagnosis")
        summary = payload.get("summary")
        if diagnosis is not None:
            existing.last_summary = str(diagnosis)
        elif summary is not None:
            existing.last_summary = str(summary)

        related_files = payload.get("related_files") or []
        if isinstance(related_files, list):
            existing.related_files = _dedupe_keep_order(
                existing.related_files + [str(x) for x in related_files]
            )

        self._state.failure_patterns[signature] = existing
        self.save()
        return existing

    # -------------------------------------------------------------------------
    # Patch provenance / metrics / runs
    # -------------------------------------------------------------------------

    def recent_patch_provenance(self, limit: int = 25) -> list[PatchProvenance]:
        history = self._state.patch_provenance or []
        if limit <= 0:
            return []
        return history[-limit:]

    def recent_runs(self, limit: int = 6) -> list[RunRecord]:
        runs = self._state.runs or []
        if limit <= 0:
            return []
        return runs[-limit:]

    def has_recent_patch_fingerprint(self, fingerprint: str, window: int = 12) -> bool:
        if not fingerprint or window <= 0:
            return False

        recent_events = self._state.improvement_history[-window:] if self._state.improvement_history else []
        for event in recent_events:
            if not isinstance(event, dict):
                continue
            if event.get("type") != "patch_observation":
                continue
            if event.get("patch_fingerprint") == fingerprint:
                return True

        return False

    def has_recent_patch_path(self, path: str, window: int = 8) -> bool:
        normalized = (path or "").strip()
        if not normalized or window <= 0:
            return False

        for entry in self.recent_patch_provenance(limit=window):
            if getattr(entry, "path", "") == normalized:
                return True

        return False

    def record_patch(
        self,
        run_id: str,
        mode: str,
        path: str,
        description: str,
        route: str,
        source: str = "reviewer",
        patch_fingerprint: str | None = None,
    ) -> PatchProvenance:
        entry = PatchProvenance(
            run_id=run_id,
            mode=mode,
            path=path,
            description=description,
            route=route,
            source=source,
        )
        self._state.patch_provenance.append(entry)

        if patch_fingerprint:
            self._state.improvement_history.append(
                {
                    "type": "patch_observation",
                    "run_id": run_id,
                    "path": path,
                    "route": route,
                    "source": source,
                    "patch_fingerprint": patch_fingerprint,
                    "created_at": _utc_now(),
                }
            )

        self.save()
        return entry

    def record_metrics(self, entry: MetricsLedgerEntry) -> MetricsLedgerEntry:
        self._state.metrics_ledger.append(entry)

        # Legacy learning-weight feedback support, only if present on the model.
        weights = getattr(self._state, "learning_weights", None)
        if weights is not None:
            if entry.success and hasattr(weights, "repeated_success_weight"):
                weights.repeated_success_weight *= 1.01
            elif not entry.success and hasattr(weights, "repeated_failure_weight"):
                weights.repeated_failure_weight *= 1.02

            if entry.patch_count > 5 and hasattr(weights, "per_file_patch_success_weight"):
                weights.per_file_patch_success_weight *= 0.99

            if entry.review_risk == "high" and hasattr(weights, "reviewer_outcome_weight"):
                weights.reviewer_outcome_weight *= 0.98

            if hasattr(weights, "stale_advice_decay"):
                weights.stale_advice_decay *= 0.999

        self.save()
        return entry

    def add_run(self, record: RunRecord) -> RunRecord:
        self._state.runs.append(record)
        self.save()
        return record

    def get_patch_success_rate(self, path: str) -> float:
        total = 0
        success = 0

        for run in self._state.runs:
            patches_applied = getattr(run, "patches_applied", []) or []
            for patch in patches_applied:
                patch_path = self._extract_patch_path(patch)
                if patch_path == path:
                    total += 1
                    if getattr(run, "success", False):
                        success += 1

        if total == 0:
            return 0.5

        return success / total

    def _extract_patch_path(self, patch: Any) -> str | None:
        if isinstance(patch, dict):
            value = patch.get("path")
            return str(value) if value is not None else None

        value = getattr(patch, "path", None)
        return str(value) if value is not None else None

    # -------------------------------------------------------------------------
    # Backlog / reputation
    # -------------------------------------------------------------------------

    def add_backlog_items(self, items: list[str]) -> list[str]:
        self._state.backlog = _dedupe_keep_order(
            self._state.backlog + [str(item) for item in items]
        )
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

        rep.updated_at = _utc_now()
        self._state.reputations[actor] = rep
        self.save()
        return rep

    # -------------------------------------------------------------------------
    # Store IO
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # State coercion / repair
    # -------------------------------------------------------------------------

    def _coerce_state(self, raw: Any) -> MemoryState:
        if isinstance(raw, MemoryState):
            return raw

        if not isinstance(raw, dict):
            state = MemoryState()
            if not state.schema_version:
                state.schema_version = MEMORY_SCHEMA_VERSION
            return state

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
                    state.architecture_reviews.append(
                        ArchitectureReview.model_validate(item)
                    )
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
                        state.failure_patterns[signature] = FailurePatternRecord(
                            signature=signature
                        )
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
            state.schema_version = MEMORY_SCHEMA_VERSION

        if not getattr(state, "last_saved_at", None):
            state.last_saved_at = _utc_now()

        return state
