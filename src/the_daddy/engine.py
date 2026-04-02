from __future__ import annotations

import subprocess
from datetime import datetime, timezone

from .agents.diagnoser import Diagnoser
from .agents.improvement_planner import ImprovementPlanner
from .agents.reviewer import WakeReviewer
from .config import Settings, get_settings
from .git_tools import GitBranchExecutor
from .memory.r2_store import R2Store
from .memory.repository import MemoryRepository
from .merge_rules import AutoMergeJudge
from .models import MetricsLedgerEntry, RunRecord
from .policy import classify_patch_risk
from .runtime.command_runner import run_command
from .runtime.file_tools import apply_patch_action
from .scoring import rank_patch_set


def make_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class DaddyEngine:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.store = R2Store(self.settings)
        self.memory = MemoryRepository(self.store)

        self.reviewer = WakeReviewer(self.settings)
        self.planner = ImprovementPlanner()
        self.diagnoser = Diagnoser(self.settings)
        self.merge_judge = AutoMergeJudge()

        self.git_tools = GitBranchExecutor(
            repo_root=self.settings.target_root,
            github_token=self.settings.github_token,
            github_repo=self.settings.github_repo,
        )

    def repo_fingerprint(self):
        try:
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=self.settings.target_root,
                text=True,
            ).strip()
        except Exception:
            head = "unknown"
        return {"git_head": head}

    def choose_mode(self, review):
        return self.planner.decide_mode(self.memory, review)

    def _score_patch_set(self, patches: list):
        scored = rank_patch_set(patches)

        return {
            "total_score": scored.total_score,
            "recommended_route": scored.recommended_route,
            "reasons": list(scored.reasons),
        }

    def _patch_fingerprint(self, patch) -> str:
        payload = "|".join(
            [
                getattr(patch, "path", "") or "",
                getattr(patch, "operation", "") or "",
                getattr(patch, "new_content", "") or "",
                getattr(patch, "pattern", "") or "",
                getattr(patch, "replacement", "") or "",
            ]
        )
        return self.memory.fingerprint(payload)

    def _recent_patch_entries(self, limit: int = 25):
        history = getattr(self.memory.state, "patch_provenance", []) or []
        return history[-limit:]

    def _recent_runs(self, limit: int = 6):
        runs = getattr(self.memory.state, "runs", []) or []
        return runs[-limit:]

    def _is_doc_only_patch(self, patch) -> bool:
        path = (getattr(patch, "path", "") or "").lower()
        doc_exts = (".md", ".txt", ".rst")
        return path.endswith(doc_exts)

    def _has_recent_failure_pressure(self) -> bool:
        recent_runs = self._recent_runs(limit=4)
        if any(not getattr(run, "success", False) for run in recent_runs):
            return True

        ranked_failures = self.memory.ranked_failure_patterns()
        if ranked_failures and getattr(ranked_failures[0], "failure_count", 0) > 0:
            return True

        backlog = getattr(self.memory.state, "backlog", []) or []
        technical_markers = ("fix", "bug", "test", "import", "failure", "error", "patch", "runtime", "schema")
        for item in backlog[-10:]:
            text = str(item).lower()
            if any(marker in text for marker in technical_markers):
                return True

        return False

    def _patch_seen_recently(self, patch, window: int = 12) -> bool:
        fingerprint = self._patch_fingerprint(patch)
        for entry in self._recent_patch_entries(limit=window):
            if getattr(entry, "description", "") == fingerprint:
                return True
        return False

    def _path_seen_recently(self, path: str, window: int = 8) -> bool:
        normalized = (path or "").strip()
        if not normalized:
            return False
        for entry in self._recent_patch_entries(limit=window):
            if getattr(entry, "path", "") == normalized:
                return True
        return False

    def _filter_low_value_patches(self, patches: list):
        accepted = []
        filtered_reasons: list[str] = []

        recent_failure_pressure = self._has_recent_failure_pressure()

        for patch in patches:
            path = getattr(patch, "path", "") or ""

            if self._patch_seen_recently(patch):
                filtered_reasons.append(f"blocked repeated patch fingerprint: {path}")
                continue

            if self._path_seen_recently(path) and not recent_failure_pressure:
                filtered_reasons.append(f"blocked recent repeat on same path without failure pressure: {path}")
                continue

            if self._is_doc_only_patch(patch) and not recent_failure_pressure:
                filtered_reasons.append(f"blocked doc-only maintenance patch without failure pressure: {path}")
                continue

            accepted.append(patch)

        return accepted, filtered_reasons

    def _apply_safe_patches(self, run_id: str, mode: str, patches: list):
        applied = []

        if not patches:
            return applied, "none"

        filtered_patches, filter_reasons = self._filter_low_value_patches(patches)
        if not filtered_patches:
            if filter_reasons:
                print("[PATCH FILTER] " + " | ".join(filter_reasons), flush=True)
            return applied, "recommend"

        if filter_reasons:
            print("[PATCH FILTER] " + " | ".join(filter_reasons), flush=True)

        scoring = self._score_patch_set(filtered_patches)

        if scoring["recommended_route"] == "reject":
            return applied, "reject"

        policy = classify_patch_risk(filtered_patches)

        if not policy.passed:
            return applied, policy.route

        if scoring["recommended_route"] in {"branch", "recommend"}:
            return applied, scoring["recommended_route"]

        for patch in filtered_patches:
            apply_patch_action(self.settings.target_root, patch, self.settings.allow_extensions)

            self.memory.record_patch(
                run_id,
                mode,
                patch.path,
                self._patch_fingerprint(patch),
                policy.route,
            )

            applied.append(
                {
                    "path": patch.path,
                    "description": patch.description,
                    "route": policy.route,
                }
            )

        return applied, policy.route

    def run(self):
        run_id = make_run_id()

        record = RunRecord(run_id=run_id, command=self.settings.command)
        record.repo_fingerprint = self.repo_fingerprint()

        latest = self.memory.latest_review()

        review = self.reviewer.review(
            memory_snapshot=self.memory.state.model_dump(mode="json"),
            repo_root=self.settings.target_root,
            recent_summary=(latest.diagnosis if latest else ""),
        )

        self.memory.add_architecture_review(review)

        mode = self.choose_mode(review)
        record.selected_mode = mode
        record.architecture_review = review

        patches = []

        if mode == "build":
            for action in getattr(review, "self_evolution_actions", []) or []:
                if action.patches:
                    patches.extend(action.patches)

        record.patches_applied, policy_route = self._apply_safe_patches(run_id, mode, patches)

        if policy_route == "none":
            policy_route = "safe"

        result = run_command(
            self.settings.command,
            cwd=self.settings.target_root,
            timeout_seconds=self.settings.run_timeout_seconds,
        )

        record.verification = result

        if result.returncode == 0:
            record.success = True
            record.summary = "Success"
        else:
            sig = self.memory.fingerprint((result.stderr or result.stdout)[:2000])

            self.memory.record_failure_pattern(
                sig,
                {"route": mode, "diagnosis": "run failure"},
                False,
            )

            record.success = False
            record.summary = f"build: failed ({result.returncode}) but continuing"

        self.memory.record_metrics(
            MetricsLedgerEntry(
                run_id=run_id,
                mode=mode,
                success=record.success,
                review_risk=review.risk_level,
                policy_route=policy_route,
                patch_count=len(record.patches_applied),
                self_evolution_count=len(review.self_evolution_actions),
                build_actions_count=len(review.build_actions),
                architecture_plans_count=len(review.architecture_plans),
            )
        )

        self.memory.add_run(record)
        self.memory.save()

        return record
