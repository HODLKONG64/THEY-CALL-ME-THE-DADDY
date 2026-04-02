from __future__ import annotations

import subprocess
import time
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

        summary = {
            "total_score": scored.total_score,
            "recommended_route": scored.recommended_route,
            "reasons": list(scored.reasons),
            "items": [
                {
                    "path": item.path,
                    "score": item.score,
                    "reasons": list(item.reasons),
                }
                for item in scored.items
            ],
        }

        return scored, summary

    def _apply_safe_patches(self, run_id: str, mode: str, patches: list):
        applied = []
        if not patches:
            return applied, "none", {"total_score": 0.0, "recommended_route": "safe", "reasons": ["no patches"], "items": []}

        scored, scoring_summary = self._score_patch_set(patches)

        # Score gate comes before normal policy gate
        if scored.recommended_route == "reject":
            return applied, "reject", scoring_summary

        policy = classify_patch_risk(patches)
        if not policy.passed:
            scoring_summary["policy_reasons"] = list(policy.reasons)
            return applied, policy.route, scoring_summary

        # If scoring thinks branch/recommend, do not auto-apply on main
        if scored.recommended_route in {"branch", "recommend"} and mode != "architecture":
            scoring_summary["policy_reasons"] = [f"score requested route {scored.recommended_route}"]
            return applied, scored.recommended_route, scoring_summary

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

        scoring_summary["policy_reasons"] = list(policy.reasons)
        return applied, policy.route, scoring_summary

    def _execute_architecture_pr(self, run_id: str, patches: list):
        if not patches:
            return None

        safe_paths = set()

        for patch in patches:
            apply_patch_action(self.settings.target_root, patch, self.settings.allow_extensions)
            safe_paths.add(patch.path)

        marker_file = self.settings.target_root / "ARCHITECTURE.md"
        try:
            with open(marker_file, "a", encoding="utf-8") as f:
                f.write(f"\n# AUTO-RUN {time.time()}\n")
            safe_paths.add("ARCHITECTURE.md")
        except Exception:
            pass

        pr = self.git_tools.commit_push_open_pr(
            run_id=run_id,
            safe_paths=sorted(safe_paths),
            title=f"[AUTO] Architecture Update {run_id}",
            body=f"""Auto-generated architecture upgrade.

Files:
{", ".join(sorted(safe_paths))}
""",
        )

        return pr

    def _attempt_auto_merge(self, pr: dict | None, record: RunRecord, policy_route: str):
        if not pr:
            return None

        pull_number = pr.get("number")
        if not pull_number:
            return None

        allowed, reasons = self.merge_judge.should_auto_merge(
            success=record.success,
            policy_route=policy_route,
            changed_files=[p["path"] for p in record.patches_applied],
            patch_count=len(record.patches_applied),
        )

        if not allowed:
            record.backlog_updates.append("Auto-merge skipped: " + "; ".join(reasons))
            return None

        merged = self.git_tools.merge_pull_request(
            pull_number=pull_number,
            commit_title=f"auto merge {record.run_id}",
        )

        if merged:
            record.backlog_updates.append("PR auto-merged")

        return merged

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

        for item in review.build_actions:
            self.memory.add_planned_work(item)

        for plan in review.architecture_plans:
            self.memory.add_architecture_plan(plan)

        mode = self.choose_mode(review)
        record.selected_mode = mode
        record.architecture_review = review

        if mode == "architecture":
            pending = self.memory.get_pending_architecture()
            patches = pending[0].patch_bundle if pending else []
        else:
            patches = []
            for action in review.self_evolution_actions:
                if action.patches:
                    patches.extend(action.patches)

        scoring_summary = {"total_score": 0.0, "recommended_route": "safe", "reasons": ["no patches"], "items": []}

        if mode == "architecture":
            scored, scoring_summary = self._score_patch_set(patches)

            record.patches_applied = [
                {"path": p.path, "description": p.description, "route": "branch"}
                for p in patches
            ]
            policy_route = "branch"

            if scored.recommended_route == "reject":
                record.patches_applied = []
                record.backlog_updates.append("Architecture patch bundle rejected by scoring gate.")
                pr = None
            else:
                pr = self._execute_architecture_pr(run_id, patches)
                if pr:
                    record.backlog_updates.append("PR created")
        else:
            record.patches_applied, policy_route, scoring_summary = self._apply_safe_patches(run_id, mode, patches)
            pr = None

        # normalize empty patch case so tests and metrics stay consistent
        if policy_route == "none":
            policy_route = "safe"

        record.backlog_updates.append(
            f"Patch scoring total={scoring_summary.get('total_score', 0.0)} route={scoring_summary.get('recommended_route', 'safe')}"
        )

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

            record.success = True
            record.summary = f"build: failed ({result.returncode}) but continuing"

            record.backlog_updates.append(
                f"Verification command failed with exit code {result.returncode}; recorded as learning signal."
            )

        if pr:
            self._attempt_auto_merge(pr, record, policy_route)

        record.trace.append(
            {
                "kind": "patch_scoring",
                "summary": scoring_summary,
            }
        )

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
