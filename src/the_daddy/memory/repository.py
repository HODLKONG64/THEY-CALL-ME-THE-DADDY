from __future__ import annotations

import hashlib
import json
from typing import Any

from .r2_store import R2Store


class MemoryRepository:
    def __init__(self, store: R2Store):
        self.store = store
        self.state = self._load()

    # ======================
    # CORE LOAD / SAVE
    # ======================

    def _load(self) -> dict[str, Any]:
        try:
            data = self.store.load()
            if isinstance(data, dict):
                return data
        except Exception:
            pass

        return {
            "runs": [],
            "patch_history": [],
            "failure_patterns": {},
            "metrics": [],
            "planned_work": [],
            "architecture_queue": [],
        }

    def save(self):
        self.store.save(self.state)

    # ======================
    # FINGERPRINT (FIX)
    # ======================

    def fingerprint(self, text: str) -> str:
        if not text:
            return "empty"
        return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

    # ======================
    # RUN STORAGE
    # ======================

    def add_run(self, run):
        self.state.setdefault("runs", []).append(run.model_dump())

    # ======================
    # PATCH TRACKING
    # ======================

    def record_patch(self, run_id, mode, path, description, route):
        self.state.setdefault("patch_history", []).append(
            {
                "run_id": run_id,
                "mode": mode,
                "path": path,
                "description": description,
                "route": route,
            }
        )

    # ======================
    # FAILURE LEARNING
    # ======================

    def record_failure_pattern(self, signature: str, context: dict, resolved: bool):
        self.state.setdefault("failure_patterns", {})[signature] = {
            "context": context,
            "resolved": resolved,
        }

    # ======================
    # METRICS
    # ======================

    def record_metrics(self, entry):
        self.state.setdefault("metrics", []).append(entry.model_dump())

    # ======================
    # BUILD QUEUE
    # ======================

    def add_planned_work(self, item):
        self.state.setdefault("planned_work", []).append(item.model_dump())

    def get_active_work(self):
        work = self.state.get("planned_work", [])
        return [w for w in work if w.get("state") != "completed"]

    # ======================
    # ARCHITECTURE QUEUE
    # ======================

    def add_architecture_plan(self, plan):
        self.state.setdefault("architecture_queue", []).append(plan.model_dump())

    def get_pending_architecture(self):
        plans = self.state.get("architecture_queue", [])
        return [p for p in plans if p.get("status") == "proposed"]

    def update_architecture_status(self, title: str, status: str):
        for plan in self.state.get("architecture_queue", []):
            if plan.get("title") == title:
                plan["status"] = status