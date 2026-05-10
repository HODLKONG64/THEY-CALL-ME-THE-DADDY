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
    RunLearningLedgerEntry,
    RunRecord,
    VettingDecision,
    utc_now_iso,
)
from ..runtime.redaction import sanitize_list, sanitize_mapping, sanitize_text

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

    def add_run_learning_entry(self, entry: RunLearningLedgerEntry) -> RunLearningLedgerEntry:
        self._state.run_learning_ledger.append(entry)
        # bound growth to keep memory compact
        self._state.run_learning_ledger = self._state.run_learning_ledger[-500:]
        self.save()
        return entry

    def latest_run_learning_entries(self, limit: int = 10) -> list[RunLearningLedgerEntry]:
        return list(self._state.run_learning_ledger[-max(1, int(limit)):])

    def ranked_recurring_blockers(self) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for item in self._state.run_learning_ledger:
            reason = sanitize_text(str(getattr(item, "blocked_reason", "") or "").strip())
            if not reason:
                continue
            counts[reason] = counts.get(reason, 0) + 1
        ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
        return [{"blocked_reason": reason, "count": count} for reason, count in ranked[:20]]

    def advice_actionability_stats(self) -> dict[str, Any]:
        items = list(self._state.run_learning_ledger or [])
        total = len(items)
        advice_actionable_count = sum(
            1 for i in items if str(getattr(i, "outcome", "")) in {"success_with_patch", "clean_no_action"}
        )
        patch_attempted_count = sum(1 for i in items if int(getattr(i, "attempted_patch_count", 0) or 0) > 0)
        verified_progress_count = sum(1 for i in items if str(getattr(i, "outcome", "")) == "success_with_patch")
        clean_no_action_count = sum(1 for i in items if str(getattr(i, "outcome", "")) == "clean_no_action")
        blocked_or_failed_count = sum(
            1
            for i in items
            if str(getattr(i, "outcome", "")) in {
                "verification_failed",
                "attempted_patch_failed",
                "policy_rejected",
                "git_pr_lane_failed",
                "blocked_fake_noop",
            }
        )
        advice_not_actionable_count = sum(
            1 for i in items if str(getattr(i, "outcome", "")) == "advice_not_actionable"
        )
        fake_noop_blocked_count = sum(1 for i in items if str(getattr(i, "outcome", "")) == "blocked_fake_noop")
        return {
            "total": total,
            "advice_actionable_count": advice_actionable_count,
            "patch_attempted_count": patch_attempted_count,
            "verified_progress_count": verified_progress_count,
            "clean_no_action_count": clean_no_action_count,
            "blocked_or_failed_count": blocked_or_failed_count,
            "advice_not_actionable_count": advice_not_actionable_count,
            "fake_noop_blocked_count": fake_noop_blocked_count,
        }

    def summarize_recent_learning(self, limit: int = 10) -> dict[str, Any]:
        recent = self.latest_run_learning_entries(limit=limit)
        outcomes = [str(item.outcome) for item in recent]
        subsystems = [str(item.subsystem) for item in recent if str(item.subsystem)]
        failed_files: dict[str, int] = {}
        avoid_lessons: list[str] = []
        successful_patterns: list[str] = []
        for item in recent:
            for path in item.files_involved:
                failed_files[path] = failed_files.get(path, 0) + 1
            for lesson in item.avoid_next_time:
                if lesson and lesson not in avoid_lessons:
                    avoid_lessons.append(lesson)
            if item.outcome == "success_with_patch":
                for worked in item.what_worked:
                    if worked and worked not in successful_patterns:
                        successful_patterns.append(worked)

        ranked_files = sorted(failed_files.items(), key=lambda x: (-x[1], x[0]))
        return sanitize_mapping({
            "recent_outcomes": outcomes[-5:],
            "recurring_blockers": self.ranked_recurring_blockers()[:5],
            "repeated_files": [{"path": p, "count": c} for p, c in ranked_files[:5]],
            "subsystems": subsystems[-10:],
            "avoid_next_time": sanitize_list(avoid_lessons[:10]),
            "successful_patterns": sanitize_list(successful_patterns[:10]),
            "advice_actionability": self.advice_actionability_stats(),
        })

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

            for item in raw.get("run_learning_ledger", []) or []:
                try:
                    state.run_learning_ledger.append(RunLearningLedgerEntry.model_validate(item))
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
