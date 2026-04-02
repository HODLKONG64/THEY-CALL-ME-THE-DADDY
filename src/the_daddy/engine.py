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
            "items": [
                {
                    "path": item.path,
                    "score": item.score,
                    "reasons": list(item.reasons),
                }
                for item in getattr(scored, "items", []) or []
            ],
        }

    def _apply_safe_patches(self, run_id: str, mode: str, patches: list, record: RunRecord):
        applied = []
        rollback_manifest = []

        if not patches:
            record.trace.append(
                {
                    "event": "patch_scoring",
                    "result": "no_patches",
                }
            )
            return applied, rollback_manifest, "none"

        scoring = self._score_patch_set(patches)
        record.trace.append(
            {
                "event": "patch_scoring",
                "recommended_route": scoring["recommended_route"],
                "total_score": scoring["total_score"],
                "reasons": scoring["reasons"],
                "items": scoring["items"],
            }
        )

        if scoring["recommended_route"] == "reject":
            return applied, rollback_manifest, "reject"

        policy = classify_patch_risk(patches)
        record.trace.append(
            {
                "event": "patch_policy",
                "passed": policy.passed,
                "route": policy.route,
                "reasons": list(policy.reasons),
            }
        )

        if not policy.passed:
            return applied, rollback_manifest, policy.route

        if scoring["recommended_route"] in {"branch", "recommend"}:
            return applied, rollback_manifest, scoring["recommended_route"]

        for patch in patches:
            try:
                result = apply_patch_action(
                    self.settings.target_root,
                    patch,
                    self.settings.allow_extensions,
                )
            except Exception as exc:
                record.trace.append(
                    {
                        "event": "patch_apply_failed",
                        "path": getattr(patch, "path", ""),
                        "description": getattr(patch, "description", ""),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                self.memory.record_failure_pattern(
                    self.memory.fingerprint(f"{patch.path}:{type(exc).__name__}:{str(exc)}"),
                    {
                        "route": mode,
                        "diagnosis": "patch application rejected",
                        "summary": str(exc),
                        "related_files": [getattr(patch, "path", "")],
                    },
                    False,
                )
                continue

            self.memory.record_patch(
                run_id,
                mode,
                patch.path,
                patch.description,
                policy.route,
            )

            applied.append(
                {
                    "path": patch.path,
                    "description": patch.description,
                    "route": policy.route,
                    "bytes_before": result["bytes_before"],
                    "bytes_after": result["bytes_after"],
                }
            )

            rollback_manifest.append(
                {
                    "path": result["rollback"]["path"],
                    "old_hash": result["rollback"]["old_hash"],
                    "old_content": result["rollback"]["old_content"],
                }
            )

            record.trace.append(
                {
                    "event": "patch_applied",
                    "path": result["path"],
                    "description": patch.description,
                    "bytes_before": result["bytes_before"],
                    "bytes_after": result["bytes_after"],
                }
            )

        return applied, rollback_manifest, policy.route

    def _changed_files_from_record(self, record: RunRecord) -> list[str]:
        files: list[str] = []
        for item in getattr(record, "patches_applied", []) or []:
            if isinstance(item, dict):
                path = item.get("path")
            else:
                path = getattr(item, "path", None)
            if isinstance(path, str) and path and path not in files:
                files.append(path)
        return files

    def _total_byte_delta_from_record(self, record: RunRecord) -> int:
        total = 0
        for item in getattr(record, "patches_applied", []) or []:
            if isinstance(item, dict):
                before = int(item.get("bytes_before", 0) or 0)
                after = int(item.get("bytes_after", 0) or 0)
                total += abs(after - before)
        return total

    def _build_pr_title(self, run_id: str, changed_files: list[str]) -> str:
        if len(changed_files) == 1:
            return f"auto: daddy fix {run_id} ({changed_files[0]})"
        return f"auto: daddy fix {run_id}"

    def _build_pr_body(self, record: RunRecord, policy_route: str, changed_files: list[str]) -> str:
        review = getattr(record, "architecture_review", None)
        risk = getattr(review, "risk_level", "") if review is not None else ""
        summary = getattr(record, "summary", "") or "Automated bounded patch set."
        total_delta = self._total_byte_delta_from_record(record)

        body_lines = [
            "## Daddy automated patch",
            "",
            f"- Run ID: `{record.run_id}`",
            f"- Mode: `{record.selected_mode}`",
            f"- Policy route: `{policy_route}`",
            f"- Review risk: `{risk}`",
            f"- Verification success: `{record.success}`",
            f"- Patch count: `{len(getattr(record, 'patches_applied', []) or [])}`",
            f"- Byte delta: `{total_delta}`",
            "",
            "### Summary",
            summary,
            "",
            "### Changed files",
        ]

        if changed_files:
            body_lines.extend([f"- `{path}`" for path in changed_files])
        else:
            body_lines.append("- None")

        verification = getattr(record, "verification", None)
        if verification is not None:
            body_lines.extend(
                [
                    "",
                    "### Verification",
                    f"- Return code: `{getattr(verification, 'returncode', None)}`",
                    f"- Timed out: `{getattr(verification, 'timed_out', False)}`",
                ]
            )

        return "\n".join(body_lines)

    def _is_git_repo(self) -> bool:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.settings.target_root,
                capture_output=True,
                text=True,
                check=False,
            )
            return result.returncode == 0 and result.stdout.strip() == "true"
        except Exception:
            return False

    def _can_use_pr_lane(self, record: RunRecord) -> tuple[bool, str]:
        if not getattr(record, "patches_applied", None):
            return False, "no_patches_applied"

        if not getattr(record, "success", False):
            return False, "verification_failed"

        if not self.settings.has_github:
            return False, "github_not_configured"

        if not self._is_git_repo():
            return False, "target_root_not_git_repo"

        changed_files = self._changed_files_from_record(record)
        if not changed_files:
            return False, "no_changed_files"

        return True, "ok"

    def _deliver_patch_via_pr(self, record: RunRecord, policy_route: str, prepared_branch: str | None = None) -> None:
        changed_files = self._changed_files_from_record(record)

        if not changed_files:
            record.trace.append(
                {
                    "event": "pr_skipped",
                    "reason": "no_changed_files",
                }
            )
            return

        branch_name = prepared_branch
        if not branch_name:
            branch_name = self.git_tools.prepare_branch(record.run_id)
            record.trace.append(
                {
                    "event": "branch_prepared",
                    "branch_name": branch_name,
                    "source": "pr_delivery_fallback",
                }
            )

        committed_branch = self.git_tools.commit_current_branch_changes(record.run_id, changed_files)

        if not committed_branch:
            record.trace.append(
                {
                    "event": "pr_skipped",
                    "reason": "no_pr_created",
                    "changed_files": changed_files,
                }
            )
            return

        title = self._build_pr_title(record.run_id, changed_files)
        body = self._build_pr_body(record, policy_route, changed_files)

        pr = self.git_tools.create_pull_request(
            branch_name=committed_branch,
            title=title,
            body=body,
            base_branch="main",
        )

        if not pr:
            record.trace.append(
                {
                    "event": "pr_skipped",
                    "reason": "no_pr_created",
                    "changed_files": changed_files,
                }
            )
            return

        pr_number = pr.get("number")
        pr_url = pr.get("html_url") or pr.get("url")

        record.trace.append(
            {
                "event": "pr_opened",
                "pr_number": pr_number,
                "pr_url": pr_url,
                "changed_files": changed_files,
            }
        )

        should_merge, reasons = self.merge_judge.should_auto_merge(
            success=record.success,
            policy_route=policy_route,
            changed_files=changed_files,
            patch_count=len(record.patches_applied),
            total_byte_delta=self._total_byte_delta_from_record(record),
            review_risk=getattr(getattr(record, "architecture_review", None), "risk_level", ""),
        )

        record.trace.append(
            {
                "event": "merge_judgement",
                "allowed": should_merge,
                "reasons": reasons,
            }
        )

        if not should_merge:
            record.trace.append(
                {
                    "event": "pr_left_open",
                    "pr_number": pr_number,
                    "reasons": reasons,
                }
            )
            return

        if not pr_number:
            record.trace.append(
                {
                    "event": "pr_merge_failed",
                    "reason": "missing_pr_number",
                }
            )
            return

        merge_result = self.git_tools.merge_pull_request(
            pull_number=pr_number,
            commit_title=f"auto: daddy merge {record.run_id}",
        )

        if merge_result:
            record.trace.append(
                {
                    "event": "pr_merged",
                    "pr_number": pr_number,
                    "result": merge_result,
                }
            )
        else:
            record.trace.append(
                {
                    "event": "pr_merge_failed",
                    "pr_number": pr_number,
                }
            )

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
        record.trace.append(
            {
                "event": "proposed_actions",
                "actions": [
                    {
                        "title": action.title,
                        "risk": action.risk,
                        "patch_paths": [patch.path for patch in action.patches],
                    }
                    for action in getattr(review, "self_evolution_actions", []) or []
                ],
            }
        )

        patches = []
        prepared_branch: str | None = None

        if mode == "build":
            for action in getattr(review, "self_evolution_actions", []) or []:
                if action.patches:
                    patches.extend(action.patches)

        if patches and self.settings.has_github and self._is_git_repo():
            try:
                prepared_branch = self.git_tools.prepare_branch(run_id)
                record.trace.append(
                    {
                        "event": "branch_prepared",
                        "branch_name": prepared_branch,
                        "source": "pre_apply",
                    }
                )
            except Exception as exc:
                record.trace.append(
                    {
                        "event": "branch_prepare_failed",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                prepared_branch = None

        (
            record.patches_applied,
            record.rollback_manifest,
            policy_route,
        ) = self._apply_safe_patches(run_id, mode, patches, record)

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

        can_use_pr_lane, pr_reason = self._can_use_pr_lane(record)
        if can_use_pr_lane:
            try:
                self._deliver_patch_via_pr(record, policy_route, prepared_branch=prepared_branch)
            except Exception as exc:
                record.trace.append(
                    {
                        "event": "pr_delivery_failed",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
        else:
            record.trace.append(
                {
                    "event": "pr_skipped",
                    "reason": pr_reason,
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
