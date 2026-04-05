from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# --- PATH RESOLVER (OPENAI TARGET FIX) ---
def _resolve_upgrade_path(path: str) -> str:
    if not isinstance(path, str):
        return path
    return path.replace('the_***', 'the_daddy')

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

EXECUTION_PATH_TARGETS = {
    "src/the_daddy/engine.py",
    "src/the_daddy/cli.py",
}


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
        patch_norm = _resolve_upgrade_path(self._normalize_path(patch_path)
        if not patch_norm:
            return False

        normalized_targets = [_resolve_upgrade_path(self._normalize_path(item) for item in target_files if str(item).strip()]
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

    def _required_execution_targets(self) -> list[str]:
        if not self.upgrade_advice:
            return []
        targets = [
            _resolve_upgrade_path(self._normalize_path(item)
            for item in list(self.upgrade_advice.get("target_files", []) or [])
            if str(item).strip()
        ]
        allowed = {_resolve_upgrade_path(self._normalize_path(item) for item in EXECUTION_PATH_TARGETS}
        return [target for target in targets if target in allowed]

    def _repair_mode_completion_satisfied(self, record: RunRecord) -> bool:
        required_targets = self._required_execution_targets()
        if not required_targets:
            return True
        changed_files = {_resolve_upgrade_path(self._normalize_path(path) for path in self._changed_files_from_record(record)}
        return any(path in changed_files for path in required_targets)

    def _enforce_repair_mode_targets(self, patches: list, record: RunRecord) -> list:
        if not self.repair_mode_active or not self.upgrade_advice:
            return patches

        target_files = [_resolve_upgrade_path(p) for p in list(self.upgrade_advice.get("target_files", []) or [])]
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

    def _build_forced_target_patches(self, record: RunRecord) -> list:
        record.trace.append(
            {
                "event": "forced_target_patch_generation_skipped",
                "reason": "engine/cli-only mode active; helper fallback disabled",
                "required_execution_targets": self._required_execution_targets(),
            }
        )
        return []


    def _load_runtime_rules(self) -> dict[str, Any]:
        rules_path = self.settings.target_root / "src/the_daddy/core/system_rules.json"
        try:
            return json.loads(rules_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _stuck_same_reason_limit(self) -> int:
        rules = self._load_runtime_rules()
        thresholds = rules.get("thresholds", {})
        return max(1, int(thresholds.get("stuck_same_reason_limit", 2) or 2))

    def _recent_same_blocker_count(self, blocker: str) -> int:
        if not blocker:
            return 0
        runs = list(getattr(self.memory.state, "runs", []) or [])
        count = 0
        for run in reversed(runs[-6:]):
            summary = str(getattr(run, "summary", "") or "")
            if blocker in summary:
                count += 1
            else:
                break
        return count

    def _target_file_snapshots(self) -> list[dict[str, Any]]:
        snapshots: list[dict[str, Any]] = []
        target_files = [_resolve_upgrade_path(p) for p in list(self.upgrade_advice.get("target_files", []) or [])] if self.upgrade_advice else []
        for raw_path in target_files:
            norm = _resolve_upgrade_path(self._normalize_path(raw_path)
            if not norm or not norm.startswith("src/"):
                continue
            path = self.settings.target_root / norm
            if not path.exists() or not path.is_file():
                continue
            try:
                snapshots.append(
                    {
                        "path": norm,
                        "content": path.read_text(encoding="utf-8", errors="ignore")[:20000],
                    }
                )
            except Exception:
                continue
        return snapshots

    def _doctor_takeover_patches(self, record: RunRecord) -> list:
        if not self.repair_mode_active or not self.upgrade_advice:
            return []

        blocker = "Repair mode pending required engine/cli upgrade"
        same_reason_count = self._recent_same_blocker_count(blocker)
        if same_reason_count < self._stuck_same_reason_limit():
            return []

        target_files = [_resolve_upgrade_path(p) for p in list(self.upgrade_advice.get("target_files", []) or [])]
        snapshots = self._target_file_snapshots()
        if not snapshots:
            record.trace.append(
                {
                    "event": "stuck_state_openai_escalation",
                    "reason": "no target file snapshots available for doctor takeover",
                    "target_files": target_files,
                }
            )
            return []

        blocker_payload = {
            "summary": blocker,
            "problem_type": self.upgrade_advice.get("problem_type", ""),
            "recommended_next_step": self.upgrade_advice.get("recommended_next_step", ""),
            "target_files": target_files,
            "trace_tail": (getattr(record, "trace", []) or [])[-12:],
        }

        prior_attempts = []
        for run in list(getattr(self.memory.state, "runs", []) or [])[-4:]:
            try:
                prior_attempts.append(run.model_dump(mode="json"))
            except Exception:
                prior_attempts.append({"summary": str(getattr(run, "summary", ""))})

        record.trace.append(
            {
                "event": "stuck_state_openai_escalation",
                "reason": "Agent stuck; escalated to OpenAI for exact repair guidance.",
                "target_files": target_files,
                "same_reason_count": same_reason_count,
            }
        )

        try:
            plan = self.diagnoser.diagnose(
                command=self.settings.command,
                output=json.dumps(blocker_payload, indent=2)[:80000],
                files=snapshots,
                prior_attempts=prior_attempts,
            )
        except Exception as exc:
            record.trace.append(
                {
                    "event": "doctor_takeover_failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            return []

        allowed_targets = {_resolve_upgrade_path(self._normalize_path(path) for path in target_files}
        filtered = [
            change for change in list(getattr(plan, "changes", []) or [])
            if _resolve_upgrade_path(self._normalize_path(getattr(change, "path", "")) in allowed_targets
        ]

        record.trace.append(
            {
                "event": "doctor_agent_takeover",
                "diagnosis": str(getattr(plan, "diagnosis", "")),
                "root_cause": str(getattr(plan, "root_cause", "")),
                "proposed_paths": [getattr(change, "path", "") for change in list(getattr(plan, "changes", []) or [])],
                "allowed_paths": [getattr(change, "path", "") for change in filtered],
            }
        )
        return filtered

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
            record.trace.append({"event": "patch_scoring", "result": "no_patches"})
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

        body_lines.extend(["", "### Summary", summary, "", "### Changed files"])

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
                [f"{event.get('path', '')}: {event.get('error', '')}" for event in patch_failures]
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

    def _run_depth_gate(self, *, mode: str, patches: list, record: RunRecord) -> list:
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
            record.trace.append({"event": "failure_recovery_candidate", "summary": summary})

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

        mode = "repair" if self.repair_mode_active else self.choose_mode(review)
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

        if mode in {"build", "repair"}:
            for action in getattr(review, "self_evolution_actions", []) or []:
                if action.patches:
                    patches.extend(action.patches)

        patches = self._run_depth_gate(mode=mode, patches=patches, record=record)
        patches = self._enforce_repair_mode_targets(patches, record)

        if self.repair_mode_active:
            required_execution_targets = self._required_execution_targets()
            if required_execution_targets:
                allowed_targets = set(required_execution_targets)
                patches = [
                    patch for patch in patches
                    if _resolve_upgrade_path(self._normalize_path(getattr(patch, "path", "")) in allowed_targets
                ]
                record.trace.append(
                    {
                        "event": "forced_execution_target_mode",
                        "required_execution_targets": required_execution_targets,
                        "allowed_patch_paths": [getattr(patch, "path", "") for patch in patches],
                        "helper_fallback_disabled": True,
                    }
                )

        if self.repair_mode_active and not patches:
            record.trace.append(
                {
                    "event": "repair_mode_no_patches_remaining",
                    "reason": "no valid engine/cli execution-target patch was proposed",
                    "required_execution_targets": self._required_execution_targets(),
                }
            )
            takeover_patches = self._doctor_takeover_patches(record)
            if takeover_patches:
                patches = takeover_patches

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
            if self.repair_mode_active and not self._repair_mode_completion_satisfied(record):
                record.success = False
                record.summary = "Repair mode pending required engine/cli upgrade"
                record.trace.append(
                    {
                        "event": "repair_mode_completion_blocked",
                        "reason": "required execution-path target not completed",
                        "required_execution_targets": self._required_execution_targets(),
                        "changed_files": self._changed_files_from_record(record),
                    }
                )
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
