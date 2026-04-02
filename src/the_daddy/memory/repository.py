from __future__ import annotations

import hashlib
from typing import Any

from ..models import (
    ArchitectureReview,
    FailurePatternRecord,
    MemoryState,
    MetricsLedgerEntry,
    PatchProvenance,
    RunRecord,
    utc_now_iso,
)


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

    def _load_from_store(self) -> MemoryState:
        if not self.store:
            return MemoryState()

        try:
            raw = self.store.load()
            if not raw:
                return MemoryState()
            return MemoryState.model_validate(raw)
        except Exception:
            # hard fallback (prevents crash loops)
            return MemoryState()

    def save(self):
        self._state.last_saved_at = _utc_now()

        if not self.store:
            return

        try:
            self.store.save(self._state.model_dump(mode="json"))
        except Exception:
            # do NOT silently lose data → fallback to local file
            try:
                fallback = Path("sam-memory-fallback.json")
                fallback.write_text(self._state.model_dump_json(indent=2), encoding="utf-8")
            except Exception:
                pass

    # ---------- RUNS ----------

    def add_run(self, record: RunRecord):
        record.finished_at = _utc_now()
        record.attempt_count = max(1, int(getattr(record, "attempt_count", 0) or 0) + 1)
        self._state.runs.append(record)

    def latest_review(self) -> ArchitectureReview | None:
        if not self._state.architecture_reviews:
            return None
        return self._state.architecture_reviews[-1]

    def add_architecture_review(self, review: ArchitectureReview):
        self._state.architecture_reviews.append(review)

    # ---------- PATCHES ----------

    def record_patch(
        self,
        run_id: str,
        mode: str,
        path: str,
        description: str,
        route: str,
    ):
        fingerprint = hashlib.sha256(f"{path}:{description}".encode()).hexdigest()

        self._state.patch_provenance.append(
            PatchProvenance(
                run_id=run_id,
                mode=mode,
                path=path,
                description=description,
                patch_fingerprint=fingerprint,
                route=route,
            )
        )

    # ---------- FAILURE PATTERNS ----------

    def fingerprint(self, text: str) -> str:
        return hashlib.sha256((text or "").encode()).hexdigest()

    def record_failure_pattern(
        self,
        signature: str,
        payload: dict[str, Any],
        success: bool,
    ):
        record = self._state.failure_patterns.get(signature)

        if not record:
            record = FailurePatternRecord(signature=signature)
            self._state.failure_patterns[signature] = record

        if success:
            record.success_count += 1
        else:
            record.failure_count += 1

        record.last_route = payload.get("route", "")
        record.last_summary = payload.get("summary", "") or payload.get("diagnosis", "")
        record.related_files = _dedupe_keep_order(
            record.related_files + payload.get("related_files", [])
        )
        record.updated_at = _utc_now()

    # ---------- METRICS ----------

    def record_metrics(self, entry: MetricsLedgerEntry):
        self._state.metrics_ledger.append(entry)

    # ---------- BACKLOG ----------

    def add_backlog_items(self, items: list[str]):
        combined = self._state.backlog + items
        self._state.backlog = _dedupe_keep_order(combined)
