from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any


MEMORY_SCHEMA_VERSION = 2


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


@dataclass
class DaddyMemoryState:
    schema_version: int = MEMORY_SCHEMA_VERSION
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    runs: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    failure_patterns: dict[str, dict[str, Any]] = field(default_factory=dict)

    architecture_reviews: list[dict[str, Any]] = field(default_factory=list)
    latest_architecture_review: dict[str, Any] = field(default_factory=dict)
    build_queue: list[dict[str, Any]] = field(default_factory=list)
    architecture_queue: list[dict[str, Any]] = field(default_factory=list)
    backlog: list[str] = field(default_factory=list)

    self_evolution_history: list[dict[str, Any]] = field(default_factory=list)
    proposed_builds: list[dict[str, Any]] = field(default_factory=list)

    # keep known evolving fields (optional but safe)
    improvement_history: list[dict[str, Any]] = field(default_factory=list)
    quarantine_events: list[dict[str, Any]] = field(default_factory=list)

    reputations: dict[str, dict[str, Any]] = field(default_factory=dict)
    drift_warnings: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    notes: dict[str, Any] = field(default_factory=dict)
    latest_run_summary: dict[str, Any] = field(default_factory=dict)


MemoryState = DaddyMemoryState


class MemoryRepository:
    def __init__(self, store: Any | None = None) -> None:
        self.store = store
        self._state = self._load_from_store()

    @property
    def state(self) -> DaddyMemoryState:
        return self._state

    def fingerprint(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

    def load_state(self) -> DaddyMemoryState:
        self._state = self._load_from_store()
        return self._state

    def load(self) -> DaddyMemoryState:
        return self.load_state()

    def save_state(self, state: DaddyMemoryState | dict[str, Any] | None = None) -> DaddyMemoryState:
        if state is not None:
            self._state = self._coerce_state(state)
        self._state.updated_at = _utc_now()
        self._save_to_store(self._state)
        return self._state

    def save(self, state: DaddyMemoryState | dict[str, Any] | None = None) -> DaddyMemoryState:
        return self.save_state(state)

    def snapshot(self) -> dict[str, Any]:
        return asdict(self._state)

    def record_run_summary(self, summary: dict[str, Any]) -> None:
        self._state.runs.append(dict(summary))
        self._state.latest_run_summary = dict(summary)
        if not summary.get("success", False):
            self._state.failures.append(dict(summary))
        self._bump_metric("run_count")
        if summary.get("success", False):
            self._bump_metric("successful_runs")
        else:
            self._bump_metric("failed_runs")
        self.save_state()

    def record_architecture_review(self, review: dict[str, Any]) -> None:
        payload = dict(review)
        payload.setdefault("recorded_at", _utc_now())
        self._state.architecture_reviews.append(payload)
        self._state.latest_architecture_review = payload

        backlog_items = payload.get("backlog_items") or []
        if isinstance(backlog_items, list):
            self._state.backlog = _dedupe_keep_order(self._state.backlog + [str(x) for x in backlog_items])

        self.save_state()

    def record_self_evolution(self, event: dict[str, Any]) -> None:
        payload = dict(event)
        payload.setdefault("recorded_at", _utc_now())
        self._state.self_evolution_history.append(payload)
        self._bump_metric("self_evolution_events")
        self.save_state()

    def add_backlog_items(self, items: list[str]) -> None:
        self._state.backlog = _dedupe_keep_order(self._state.backlog + [str(i) for i in items])
        self.save_state()

    def enqueue_build_action(self, action: dict[str, Any]) -> None:
        self._state.build_queue.append(dict(action))
        self.save_state()

    def enqueue_architecture_plan(self, plan: dict[str, Any]) -> None:
        self._state.architecture_queue.append(dict(plan))
        self.save_state()

    def mark_failure_pattern(self, signature: str, details: dict[str, Any] | None = None) -> None:
        if not signature:
            return
        existing = dict(self._state.failure_patterns.get(signature, {}))
        details = dict(details or {})
        entry = {
            "signature": signature,
            "first_seen_at": existing.get("first_seen_at", _utc_now()),
            "last_seen_at": _utc_now(),
            "count": int(existing.get("count", 0)) + 1,
            **existing,
            **details,
        }
        entry["signature"] = signature
        self._state.failure_patterns[signature] = entry
        self.save_state()

    def update_reputation(self, actor: str, **fields: Any) -> None:
        record = dict(self._state.reputations.get(actor, {}))
        record.update(fields)
        record.setdefault("updated_at", _utc_now())
        self._state.reputations[actor] = record
        self.save_state()

    def _load_from_store(self) -> DaddyMemoryState:
        raw: Any = {}
        if self.store is None:
            return DaddyMemoryState()

        if hasattr(self.store, "load"):
            raw = self.store.load()
        elif hasattr(self.store, "get"):
            raw = self.store.get()
        elif hasattr(self.store, "read"):
            raw = self.store.read()
        else:
            raw = {}

        return self._coerce_state(raw)

    def _save_to_store(self, state: DaddyMemoryState) -> None:
        if self.store is None:
            return

        payload = asdict(state)
        if hasattr(self.store, "save"):
            self.store.save(payload)
        elif hasattr(self.store, "put"):
            self.store.put(payload)
        elif hasattr(self.store, "write"):
            self.store.write(payload)

    def _coerce_state(self, raw: Any) -> DaddyMemoryState:
        if isinstance(raw, DaddyMemoryState):
            return raw

        if is_dataclass(raw):
            raw = asdict(raw)

        if not isinstance(raw, dict):
            return DaddyMemoryState()

        merged: dict[str, Any] = asdict(DaddyMemoryState())
        merged.update(raw)

        # FIX 1: schema_version safe coercion
        raw_version = merged.get("schema_version") or MEMORY_SCHEMA_VERSION
        try:
            if isinstance(raw_version, str) and "." in raw_version:
                merged["schema_version"] = int(float(raw_version))
            else:
                merged["schema_version"] = int(raw_version)
        except Exception:
            merged["schema_version"] = int(MEMORY_SCHEMA_VERSION)

        # FIX 2: preserve unknown fields (do NOT lose evolution data)
        allowed_fields = DaddyMemoryState.__dataclass_fields__.keys()
        extra_fields = {k: v for k, v in merged.items() if k not in allowed_fields}

        if extra_fields:
            merged.setdefault("notes", {})
            merged["notes"].setdefault("_extra", {})
            merged["notes"]["_extra"].update(extra_fields)

        filtered = {k: v for k, v in merged.items() if k in allowed_fields}

        # Defensive repairs
        for key in (
            "runs",
            "failures",
            "architecture_reviews",
            "build_queue",
            "architecture_queue",
            "backlog",
            "self_evolution_history",
            "proposed_builds",
            "drift_warnings",
        ):
            if not isinstance(filtered.get(key), list):
                filtered[key] = []

        for key in (
            "failure_patterns",
            "latest_architecture_review",
            "reputations",
            "metrics",
            "notes",
            "latest_run_summary",
        ):
            if not isinstance(filtered.get(key), dict):
                filtered[key] = {}

        return DaddyMemoryState(**filtered)

    def _bump_metric(self, key: str, amount: int = 1) -> None:
        current = self._state.metrics.get(key, 0)
        try:
            current = int(current)
        except Exception:
            current = 0
        self._state.metrics[key] = current + amount