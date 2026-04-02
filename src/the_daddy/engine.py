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
from .models import MetricsLedgerEntry, RunRecord
from .policy import classify_patch_risk
from .runtime.command_runner import run_command
from .runtime.file_tools import apply_patch_action


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

        # 👇 NEW: Git tools with PR support
        self.git_tools = GitBranchExecutor(
            repo_root=self.settings.target_root,
            github_token=self.settings.openai_api_key,  # reuse env (we’ll improve later if needed)
            github_repo=self._detect_repo(),
        )

    def _detect_repo(self) -> str:
        try:
            url = subprocess.check_output(
                ["git", "config", "--get", "remote.origin.url"],
                cwd=self.settings.target_root,
                text=True,
            ).strip()

            # supports https + ssh
            if "github.com" in url:
                return url.split("github.com/")[1].replace(".git", "")
        except Exception:
            pass
        return ""

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

    def choose_mode(self):
        if self.settings.enable_architecture_lane and self.memory.get_pending_architecture():
            return "architecture"
        if self.memory.get_active_work():
            return "build"
        return "repair"

    def _apply_safe_patches(self, run_id: str, mode: str, patches: list):
        applied = []
        if not patches:
            return applied

        policy = classify_patch_risk(patches)
        if not policy.passed:
            return applied

        for patch in patches:
            apply_patch_action(self.settings.target_root, patch, self.settings.allow_extensions)
            self.memory.record_patch(run_id, mode, patch.path, patch.description, policy.route)
            applied.append(
                {
                    "path": patch.path,
                    "description": patch.description,
                    "route": policy.route,
                }
            )
        return applied

    def _execute_architecture_pr(self, run_id: str):
        pending = self.memory.get_pending_architecture()
        if not pending:
            return None

        plan = pending[0]
        if not plan.patch_bundle:
            self.memory.update_architecture_status(plan.title, "blocked")
            return None

        safe_paths = set()

        for patch in plan.patch_bundle:
            apply_patch_action(self.settings.target_root, patch, self.settings.allow_extensions)
            safe_paths.add(patch.path)

        pr = self.git_tools.commit_push_and_open_pr(
            run_id=run_id,
            safe_paths=sorted(safe_paths),
            title=f"[AUTO] {plan.title}",
            body=f"""
Auto-generated architecture upgrade.

### Summary
{plan.summary}

### Rationale
{plan.rationale}

### Files Changed
{", ".join(safe_paths)}

### Safety
- bounded patch set
- no infra changes
- no secrets
""",
        )

        if pr:
            self.memory.update_architecture_status(plan.title, "active")

        return pr

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

        # store build + architecture ideas
        for item in review.build_actions:
            self.memory.add_planned_work(item)

        for plan in review.architecture_plans:
            self.memory.add_architecture_plan(plan)

        mode = self.choose_mode()
        record.selected_mode = mode

        # flatten patches
        patches = []
        for action in review.self_evolution_actions:
            patches.extend(action.patches)

        record.patches_applied.extend(
            self._apply_safe_patches(run_id, mode, patches)
        )

        # 👇 NEW: architecture → PR
        pr = None
        if mode == "architecture":
            pr = self._execute_architecture_pr(run_id)
            if pr:
                record.backlog_updates.append(f"PR created: {pr.get('html_url', '')}")

        # run tests
        result = run_command(self.settings.command, cwd=self.settings.target_root)

        record.verification = result
        record.success = result.returncode == 0
        record.summary = (
            "Success" if record.success else f"Failed ({result.returncode})"
        )

        # failure learning
        if not record.success:
            sig = self.memory.fingerprint((result.stderr or result.stdout)[:2000])
            self.memory.record_failure_pattern(sig, {"route": mode}, False)

        # metrics
        self.memory.record_metrics(
            MetricsLedgerEntry(
                run_id=run_id,
                mode=mode,
                success=record.success,
                review_risk=review.risk_level,
                policy_route="safe" if record.patches_applied else "none",
                patch_count=len(record.patches_applied),
                self_evolution_count=len(review.self_evolution_actions),
                build_actions_count=len(review.build_actions),
                architecture_plans_count=len(review.architecture_plans),
            )
        )

        self.memory.add_run(record)
        self.memory.save()

        return record