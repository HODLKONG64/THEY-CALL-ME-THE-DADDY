from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from typing import Any

from .agents.diagnoser import Diagnoser
from .agents.improvement_planner import ImprovementPlanner
from .agents.reviewer import WakeReviewer
from .config import Settings, get_settings
from .core.failure_recovery import (
    recent_failed_runs,
    restore_from_rollback_manifest,
    summarize_failure_recovery_state,
)
from .core.self_check import load_rules
from .core.upgrade_gate import UpgradeGateError, validate_upgrade_gate_for_settings
from .git_tools import GitBranchExecutor
from .memory.r2_store import R2Store
from .memory.repository import MemoryRepository
from .merge_rules import AutoMergeJudge
from .models import MetricsLedgerEntry, RunRecord, SelfEvolutionExecution
from .policy import classify_patch_risk
from .runtime import architecture_probe as architecture_probe_runtime
from .runtime import reviewer_fallback as reviewer_fallback_runtime
from .runtime import run_health as run_health_runtime
from .runtime import trace_summary as trace_summary_runtime
from .runtime.command_runner import run_command
from .runtime.file_tools import apply_patch_action
from .runtime.iterative_depth_learner import IterativeDepthLearner
from .runtime.learning_journal import build_learning_journal_entry
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
        self.depth_learner = IterativeDepthLearner(
            max_depth=getattr(self.settings, "max_depth", 3)
        )
        self.upgrade_advice: dict[str, Any] | None = None
        self.repair_mode_active = False

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

    def _enforce_upgrade_gate(self, record: RunRecord) -> None:
        advice = validate_upgrade_gate_for_settings(self.settings)
        self.upgrade_advice = advice
        self.repair_mode_active = bool(advice.get("repair_mode", False))
        record.trace.append(
            {
                "event": "upgrade_gate_checked",
                "allow_proceed": bool(advice.get("allow_proceed", False)),
                "repair_mode": bool(advice.get("repair_mode", False)),
                "problem_type": str(advice.get("problem_type", "")),
                "recommended_next_step": str(advice.get("recommended_next_step", "")),
                "target_files": list(advice.get("target_files", []) or []),
                "generated_at": str(advice.get("generated_at", "")),
            }
        )

    def _normalize_path(self, value: str) -> str:
        return str(value or "").replace("\\", "/").strip().lower()

    def _repair_mode_target_matches(self, patch_path: str, target_files: list[str]) -> bool:
        patch_norm = self._normalize_path(patch_path)
        if not patch_norm:
            return False

        normalized_targets = [self._normalize_path(item) for item in target_files if str(item).strip()]
        if not normalized_targets:
            return False

        for target in normalized_targets:
            if not target:
                continue
            if patch_norm == target:
                return True
            if patch_norm.endswith(target):
                return True
            if target in patch_norm:
                return True
        return False

    def _enforce_repair_mode_targets(self, patches: list, record: RunRecord) -> list:
        if not self.repair_mode_active or not self.upgrade_advice:
            return patches

        target_files = list(self.upgrade_advice.get("target_files", []) or [])
        filtered = [
            patch for patch in patches
            if self._repair_mode_target_matches(getattr(patch, "path", ""), target_files)
        ]

        record.trace.append(
            {
                "event": "repair_mode_target_filter",
                "target_files": target_files,
                "input_patch_count": len(patches),
                "output_patch_count": len(filtered),
                "input_patch_paths": [getattr(p, "path", "") for p in patches],
                "output_patch_paths": [getattr(p, "path", "") for p in filtered],
            }
        )

        if filtered:
            return filtered

        if not patches:
            record.trace.append(
                {
                    "event": "repair_mode_no_patches_generated",
                    "reason": "no candidate patches produced",
                    "target_files": target_files,
                }
            )
            return patches

        record.trace.append(
            {
                "event": "repair_mode_no_target_match",
                "reason": "no patches matched OpenAI target_files",
                "target_files": target_files,
                "input_patch_paths": [getattr(p, "path", "") for p in patches],
            }
        )
        return []

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

            patch_fingerprint = self.memory.fingerprint(
                f"{patch.path}:{patch.description}:{result['new_hash']}"
            )

            self.memory.record_patch(
                run_id,
                mode,
                patch.path,
                patch.description,
                policy.route,
                patch_fingerprint=patch_fingerprint,
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
        self_evolution = getattr(record, "self_evolution", None)

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
        ]

        if self.upgrade_advice is not None:
            body_lines.extend(
                [
                    f"- Upgrade gate approved: `{bool(self.upgrade_advice.get('allow_proceed', False))}`",
                    f"- Repair mode: `{bool(self.upgrade_advice.get('repair_mode', False))}`",
                    f"- Upgrade gate problem type: `{self.upgrade_advice.get('problem_type', '')}`",
                ]
            )

        if self_evolution is not None:
            body_lines.extend(
                [
                    f"- Self-evolution attempted: `{getattr(self_evolution, 'attempted', False)}`",
                    f"- Self-evolution applied: `{getattr(self_evolution, 'applied', False)}`",
                    f"- Self-evolution route: `{getattr(self_evolution, 'route', '')}`",
                ]
            )

        body_lines.extend(
            [
                "",
                "### Summary",
                summary,
                "",
                "### Changed files",
            ]
        )

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

    def _build_self_evolution_record(
        self,
        *,
        review,
        policy_route: str,
        patches: list,
        applied_patches: list,
        trace: list,
    ) -> SelfEvolutionExecution:
        patch_failures = [
            event for event in trace
            if isinstance(event, dict) and event.get("event") == "patch_apply_failed"
        ]
        notes = [str(note) for note in getattr(review, "execution_notes", []) or []]

        if patch_failures:
            notes.extend(
                [
                    f"{event.get('path', '')}: {event.get('error', '')}"
                    for event in patch_failures
                ]
            )

        attempted = bool(patches)
        applied = bool(applied_patches)

        if applied:
            summary = "Applied bounded self-evolution patch set."
        elif attempted and patch_failures:
            summary = "Self-evolution attempted but all proposed patches were blocked."
        elif attempted:
            summary = "Self-evolution attempted but no patches were applied."
        else:
            summary = "No executable self-evolution action was available."

        return SelfEvolutionExecution(
            enabled=bool(getattr(self.settings, "enable_self_evolution", True)),
            attempted=attempted,
            applied=applied,
            route=policy_route,
            summary=summary,
            reasons=notes,
            proposed_count=len(getattr(review, "self_evolution_actions", []) or []),
            applied_count=len(applied_patches),
            patches=list(applied_patches),
        )

    def _run_depth_gate(
        self,
        *,
        mode: str,
        patches: list,
        record: RunRecord,
    ) -> list:
        if not patches:
            return patches

        depth_result = self.depth_learner.deepen(
            patches=[
                {
                    "path": getattr(p, "path", ""),
                    "operation": getattr(p, "operation", ""),
                    "description": getattr(p, "description", ""),
                    "new_content_length": len((getattr(p, "new_content", "") or "").encode("utf-8")),
                    "pattern": getattr(p, "pattern", None),
                }
                for p in patches
            ],
            trace=getattr(record, "trace", []) or [],
            patch_count=len(patches),
            total_byte_delta=0,
        )

        record.trace.append(
            {
                "event": "iterative_depth_result",
                "decision": depth_result.get("decision", ""),
                "depth_reached": depth_result.get("depth_reached", 0),
                "reasons": depth_result.get("reasons", []),
            }
        )

        decision = depth_result.get("decision")
        if decision == "reject":
            record.trace.append(
                {
                    "event": "patch_blocked_by_depth_learning",
                    "reason": " | ".join(depth_result.get("reasons", [])),
                }
            )
            return []

        if decision == "escalate_to_branch":
            record.trace.append(
                {
                    "event": "patch_escalated_by_depth_learning",
                    "reason": " | ".join(depth_result.get("reasons", [])),
                }
            )

        return patches

    def _recover_from_previous_failures(self, record: RunRecord) -> None:
        rules = load_rules()
        thresholds = rules.get("thresholds", {})
        failed_runs = recent_failed_runs(
            self.memory.state,
            limit=int(thresholds.get("max_failure_recovery_lookback_runs", 2) or 2),
            max_success_anchors=int(thresholds.get("max_proven_success_anchors", 2) or 2),
        )
        if not failed_runs:
            return

        for failed_run in failed_runs:
            summary = summarize_failure_recovery_state(failed_run)
            record.trace.append(
                {
                    "event": "failure_recovery_candidate",
                    "summary": summary,
                }
            )

            if not summary.get("has_recovery_material", False):
                continue

            restore_result = restore_from_rollback_manifest(
                self.settings.target_root,
                failed_run.get("rollback_manifest", []),
            )
            record.trace.append(
                {
                    "event": "failure_recovery_restore_applied",
                    "from_run_id": summary.get("run_id", ""),
                    "restored_count": restore_result.get("restored_count", 0),
                    "restored_paths": restore_result.get("restored_paths", []),
                }
            )

            verification = run_command(
                self.settings.command,
                cwd=self.settings.target_root,
                timeout_seconds=self.settings.run_timeout_seconds,
            )

            record.trace.append(
                {
                    "event": "failure_recovery_verification",
                    "from_run_id": summary.get("run_id", ""),
                    "returncode": verification.returncode,
                    "timed_out": verification.timed_out,
                }
            )

            if verification.returncode == 0:
                record.trace.append(
                    {
                        "event": "failure_recovery_succeeded",
                        "from_run_id": summary.get("run_id", ""),
                    }
                )
                return

        record.trace.append(
            {
                "event": "failure_recovery_exhausted",
                "checked_failed_runs": len(failed_runs),
            }
        )

    def _rollback_current_failure(self, record: RunRecord, mode: str) -> None:
        if not getattr(record, "rollback_manifest", None):
            return

        restore_result = restore_from_rollback_manifest(
            self.settings.target_root,
            record.rollback_manifest,
        )
        record.trace.append(
            {
                "event": "current_failure_rollback_applied",
                "restored_count": restore_result.get("restored_count", 0),
                "restored_paths": restore_result.get("restored_paths", []),
            }
        )

        verification = run_command(
            self.settings.command,
            cwd=self.settings.target_root,
            timeout_seconds=self.settings.run_timeout_seconds,
        )

        record.trace.append(
            {
                "event": "current_failure_reverification",
                "returncode": verification.returncode,
                "timed_out": verification.timed_out,
            }
        )

        if verification.returncode == 0:
            record.summary = "Recovered after rollback"
        else:
            self.memory.record_failure_pattern(
                self.memory.fingerprint((verification.stderr or verification.stdout)[:2000]),
                {"route": mode, "diagnosis": "post-rollback verification failure"},
                False,
            )

    def _deliver_patch_via_pr(self, record: RunRecord, policy_route: str, prepared_branch: str | None = None) -> None:
        changed_files = self._changed_files_from_record(record)

        if not changed_files:
            record.trace.append({"event": "pr_skipped", "reason": "no_changed_files"})
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
                {"event": "pr_skipped", "reason": "no_pr_created", "changed_files": changed_files}
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
                {"event": "pr_skipped", "reason": "no_pr_created", "changed_files": changed_files}
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
                {"event": "pr_left_open", "pr_number": pr_number, "reasons": reasons}
            )
            return

        if not pr_number:
            record.trace.append({"event": "pr_merge_failed", "reason": "missing_pr_number"})
            return

        merge_result = self.git_tools.merge_pull_request(
            pull_number=pr_number,
            commit_title=f"auto: daddy merge {record.run_id}",
        )

        if merge_result:
            record.trace.append(
                {"event": "pr_merged", "pr_number": pr_number, "result": merge_result}
            )
        else:
            record.trace.append({"event": "pr_merge_failed", "pr_number": pr_number})

    def _run_payload(self, record: RunRecord) -> dict[str, Any]:
        return {
            "run_id": record.run_id,
            "success": bool(record.success),
            "selected_mode": str(record.selected_mode or ""),
            "summary": str(record.summary or ""),
            "patch_count": len(getattr(record, "patches_applied", []) or []),
        }

    def _build_action_payloads(self, review) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for item in getattr(review, "build_actions", []) or []:
            if hasattr(item, "model_dump"):
                payloads.append(item.model_dump(mode="json"))
            elif isinstance(item, dict):
                payloads.append(dict(item))
        return payloads

    def _emit_runtime_summaries(self, *, record: RunRecord, review) -> None:
        prior_runs = []
        for item in getattr(self.memory.state, "runs", []) or []:
            if hasattr(item, "model_dump"):
                prior_runs.append(item.model_dump(mode="json"))
            elif isinstance(item, dict):
                prior_runs.append(dict(item))

        run_payloads = prior_runs[-19:] + [self._run_payload(record)]
        build_action_payloads = self._build_action_payloads(review)

        summarize_trace = getattr(trace_summary_runtime, "summarize_trace", None)
        if callable(summarize_trace):
            trace_summary = summarize_trace(getattr(record, "trace", []) or [])
            record.trace.append({"event": "runtime_trace_summary", "summary": trace_summary})

        summarize_self_evolution_skips = getattr(trace_summary_runtime, "summarize_self_evolution_skips", None)
        if callable(summarize_self_evolution_skips):
            skip_summary = summarize_self_evolution_skips(
                getattr(getattr(record, "self_evolution", None), "reasons", []) or []
            )
            record.trace.append({"event": "runtime_self_evolution_skip_summary", "summary": skip_summary})

        summarize_build_action_titles = getattr(trace_summary_runtime, "summarize_build_action_titles", None)
        if callable(summarize_build_action_titles):
            build_action_summary = summarize_build_action_titles(build_action_payloads)
            record.trace.append({"event": "runtime_build_action_summary", "summary": build_action_summary})

        summarize_build_action_pressure = getattr(trace_summary_runtime, "summarize_build_action_pressure", None)
        if callable(summarize_build_action_pressure):
            build_pressure_summary = summarize_build_action_pressure(build_action_payloads)
            record.trace.append({"event": "runtime_build_pressure_summary", "summary": build_pressure_summary})
            review.execution_notes.append(
                f"Build pressure summary emitted: active={bool(build_pressure_summary.get('active', False))} pressure_score={int(build_pressure_summary.get('pressure_score', 0) or 0)} related_files={int(build_pressure_summary.get('related_files_count', 0) or 0)}."
            )

        summarize_run_health = getattr(run_health_runtime, "summarize_run_health", None)
        if callable(summarize_run_health):
            run_health_summary = summarize_run_health(run_payloads)
            record.trace.append({"event": "runtime_run_health_summary", "summary": run_health_summary})
            review.execution_notes.append(
                f"Run health summary emitted: success_rate={run_health_summary.get('success_rate', 0)} total_runs={run_health_summary.get('total_runs', 0)}."
            )

        summarize_run_velocity = getattr(run_health_runtime, "summarize_run_velocity", None)
        if callable(summarize_run_velocity):
            run_velocity_summary = summarize_run_velocity(run_payloads)
            record.trace.append({"event": "runtime_run_velocity_summary", "summary": run_velocity_summary})
            review.execution_notes.append(
                f"Run velocity summary emitted: sample_size={run_velocity_summary.get('sample_size', 0)} successes={run_velocity_summary.get('successes', 0)}."
            )

        summarize_patch_velocity = getattr(run_health_runtime, "summarize_patch_velocity", None)
        if callable(summarize_patch_velocity):
            patch_velocity_summary = summarize_patch_velocity(run_payloads)
            record.trace.append({"event": "runtime_patch_velocity_summary", "summary": patch_velocity_summary})
            review.execution_notes.append(
                f"Patch velocity summary emitted: sample_size={patch_velocity_summary.get('sample_size', 0)} runs_with_patches={patch_velocity_summary.get('runs_with_patches', 0)}."
            )

        summarize_fallback_reason_counts = getattr(reviewer_fallback_runtime, "summarize_fallback_reason_counts", None)
        if callable(summarize_fallback_reason_counts):
            fallback_reason_summary = summarize_fallback_reason_counts(
                getattr(getattr(record, "self_evolution", None), "reasons", []) or []
            )
            record.trace.append({"event": "runtime_fallback_reason_summary", "summary": fallback_reason_summary})

        summarize_architecture_targets = getattr(architecture_probe_runtime, "summarize_architecture_targets", None)
        if callable(summarize_architecture_targets):
            architecture_target_summary = summarize_architecture_targets(
                [item.get("path", "") for item in getattr(record, "patches_applied", []) or [] if isinstance(item, dict)]
            )
            record.trace.append({"event": "runtime_architecture_target_summary", "summary": architecture_target_summary})

    def run(self):
        run_id = make_run_id()

        record = RunRecord(run_id=run_id, command=self.settings.command)
        self._enforce_upgrade_gate(record)
        self._recover_from_previous_failures(record)
        record.repo_fingerprint = self.repo_fingerprint()
        record.attempt_count = 1

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

        if getattr(review, "architecture_plans", None):
            record.trace.append(
                {
                    "event": "architecture_plans_present",
                    "count": len(review.architecture_plans),
                    "titles": [getattr(plan, "title", "") for plan in review.architecture_plans],
                    "note": "Architecture plans are recorded but not auto-applied in the build lane.",
                }
            )

        patches = []
        prepared_branch: str | None = None

        if mode == "build":
            for action in getattr(review, "self_evolution_actions", []) or []:
                if action.patches:
                    patches.extend(action.patches)

        patches = self._run_depth_gate(mode=mode, patches=patches, record=record)
        patches = self._enforce_repair_mode_targets(patches, record)

        if self.repair_mode_active and not patches:
            record.trace.append(
                {
                    "event": "repair_mode_no_patches_remaining",
                    "reason": "no valid patches after filtering",
                }
            )

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

        record.patches_applied, record.rollback_manifest, policy_route = self._apply_safe_patches(
            run_id, mode, patches, record
        )

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
            self._rollback_current_failure(record, mode)

        record.self_evolution = self._build_self_evolution_record(
            review=review,
            policy_route=policy_route,
            patches=patches,
            applied_patches=record.patches_applied,
            trace=record.trace,
        )

        self._emit_runtime_summaries(record=record, review=review)

        if self.repair_mode_active and not getattr(record, "patches_applied", None):
            record.success = False
            record.summary = "Repair mode pending required upgrade"
            record.trace.append(
                {
                    "event": "repair_mode_completion_blocked",
                    "reason": "required upgrade suggestion not completed",
                    "target_files": list(self.upgrade_advice.get("target_files", []) or []) if self.upgrade_advice else [],
                }
            )

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
            record.trace.append({"event": "pr_skipped", "reason": pr_reason})

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

        learning_entry = build_learning_journal_entry(run_id=run_id, review=review, record=record)
        self.memory.state.learning_journal.append(learning_entry)
        self.memory.state.learning_journal = self.memory.state.learning_journal[-200:]

        self.memory.add_run(record)
        self.memory.save()

        return record