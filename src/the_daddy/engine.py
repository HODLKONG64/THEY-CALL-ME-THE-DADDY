# FULL NEXT-GEN ENGINE (TRIMMED COMMENT HEADER ONLY)
# integrates multi-cycle builds + architecture lane

from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime, timezone

from .config import Settings, get_settings
from .memory.r2_store import R2Store
from .memory.repository import MemoryRepository
from .agents.reviewer import WakeReviewer
from .agents.improvement_planner import ImprovementPlanner
from .agents.diagnoser import Diagnoser
from .runtime.command_runner import run_command
from .runtime.file_tools import apply_patch_action
from .policy import classify_patch_risk
from .models import RunRecord, PatchAction


def make_run_id():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class DaddyEngine:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.store = R2Store(self.settings)
        self.memory = MemoryRepository(self.store)

        self.reviewer = WakeReviewer(self.settings)
        self.planner = ImprovementPlanner()
        self.diagnoser = Diagnoser(self.settings)

    def repo_fingerprint(self):
        try:
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip()
        except Exception:
            head = "unknown"

        return {"git_head": head}

    def choose_mode(self):
        # simple first version (will evolve)
        if self.memory.get_pending_architecture():
            return "architecture"
        if self.memory.get_active_work():
            return "build"
        return "repair"

    def run(self):
        run_id = make_run_id()

        record = RunRecord(
            run_id=run_id,
            command=self.settings.command,
        )

        record.repo_fingerprint = self.repo_fingerprint()

        review = self.reviewer.review(
            memory_snapshot=self.memory.state.model_dump(mode="json"),
            repo_root=self.settings.target_root,
            recent_summary="",
        )

        self.memory.add_architecture_review(review)

        mode = self.choose_mode()
        record.selected_mode = mode

        if mode == "architecture":
            for plan in review.architecture_plans:
                self.memory.add_architecture_plan(plan)

        if mode == "build":
            for item in review.build_actions:
                self.memory.add_planned_work(item)

        # --- SELF EVOLUTION ---
        patches = []
        for action in review.self_evolution_actions:
            for p in action.patches:
                patches.append(p)

        safe_patches = []
        if patches:
            policy = classify_patch_risk(patches)
            if policy.passed:
                safe_patches = patches

        for p in safe_patches:
            apply_patch_action(self.settings.target_root, p, self.settings.allow_extensions)
            self.memory.record_patch(run_id, mode, p.path, p.description, "safe")

        # --- COMMAND RUN ---
        result = run_command(self.settings.command, cwd=self.settings.target_root)

        record.success = result.returncode == 0

        # --- FAILURE LEARNING ---
        if not record.success:
            sig = self.memory.fingerprint(result.stderr[:2000])
            self.memory.record_failure_pattern(sig, {"diagnosis": "run failure"}, False)

        self.memory.add_run(record)
        self.memory.save()

        return record