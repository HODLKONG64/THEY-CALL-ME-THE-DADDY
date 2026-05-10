from __future__ import annotations

from typing import Any

from ..models import RunLearningLedgerEntry, RunRecord
from .redaction import sanitize_list, sanitize_text


def _event_names(record: RunRecord) -> list[str]:
    return [
        str(e.get("event", "")).strip()
        for e in (record.trace or [])
        if isinstance(e, dict) and str(e.get("event", "")).strip()
    ]


def _files_involved(record: RunRecord) -> list[str]:
    out: list[str] = []
    for item in (record.patches_applied or []):
        if isinstance(item, dict):
            path = str(item.get("path", "")).strip()
            if path and path not in out:
                out.append(path)
    return out


def _attempted_patch_count(record: RunRecord, proposed_patches: list[Any]) -> int:
    if proposed_patches:
        return len(proposed_patches)
    for event in (record.trace or []):
        if isinstance(event, dict) and event.get("event") == "patch_policy":
            count = event.get("candidate_count")
            if isinstance(count, int) and count > 0:
                return count
            return 1
    return 0


def classify_outcome(
    *,
    record: RunRecord,
    policy_route: str,
    proposed_patches: list[Any],
    target_files: list[str],
    no_action_allowed: bool,
) -> str:
    patch_count = len(record.patches_applied or [])
    attempted_patch_count = _attempted_patch_count(record, proposed_patches)
    events = set(_event_names(record))

    if "pr_delivery_failed" in events or "branch_prepare_failed" in events:
        return "git_pr_lane_failed"
    if record.verification is not None and int(getattr(record.verification, "returncode", 0) or 0) != 0:
        return "verification_failed"
    if "patch_apply_failed" in events:
        return "attempted_patch_failed"
    if policy_route == "reject" or "patch_policy" in events and "patch_applied" not in events and attempted_patch_count > 0:
        return "policy_rejected"
    if patch_count > 0 and bool(record.success):
        return "success_with_patch"
    if "no_patch_blocker_recorded" in events:
        return "blocked_fake_noop"
    if target_files and patch_count == 0 and attempted_patch_count == 0:
        return "advice_not_actionable"
    if patch_count == 0 and no_action_allowed and bool(record.success):
        return "clean_no_action"
    if attempted_patch_count > 0 and patch_count == 0:
        return "attempted_patch_failed"
    return "clean_no_action"


def build_run_learning_ledger_entry(
    *,
    record: RunRecord,
    upgrade_advice: dict[str, Any] | None,
    policy_route: str,
    proposed_patches: list[Any],
    source: str = "engine",
    no_action_allowed: bool = False,
) -> RunLearningLedgerEntry:
    target_files = [str(x) for x in list((upgrade_advice or {}).get("target_files") or []) if str(x).strip()]
    events = _event_names(record)
    files = _files_involved(record)
    attempted_patch_count = _attempted_patch_count(record, proposed_patches)
    patch_count = len(record.patches_applied or [])

    outcome = classify_outcome(
        record=record,
        policy_route=policy_route,
        proposed_patches=proposed_patches,
        target_files=target_files,
        no_action_allowed=no_action_allowed,
    )

    blocked_reason = ""
    for event in (record.trace or []):
        if not isinstance(event, dict):
            continue
        if event.get("event") in {
            "no_patch_blocker_recorded",
            "repair_mode_completion_blocked",
            "openai_advice_forbidden_patch_blocked",
            "forced_target_patch_generation_skipped",
            "helper_lane_skipped_for_execution_target_repair",
        }:
            blocked_reason = sanitize_text(str(event.get("reason", "")).strip())
            if blocked_reason:
                break

    tests_run = []
    if getattr(record, "command", ""):
        tests_run.append(str(record.command))
    for item in list((upgrade_advice or {}).get("tests_to_run") or []):
        text = sanitize_text(str(item).strip())
        if text and text not in tests_run:
            tests_run.append(text)

    what_worked: list[str] = []
    what_failed: list[str] = []
    if patch_count > 0:
        what_worked.append(f"applied_patches={patch_count}")
    if bool(record.success):
        what_worked.append("verification_passed")
    if "patch_apply_failed" in events:
        what_failed.append("patch_apply_failed")
    if "no_patch_blocker_recorded" in events:
        what_failed.append("fake_noop_blocked")
    if int(getattr(getattr(record, "verification", None), "returncode", 0) or 0) != 0:
        what_failed.append("verification_failed")

    subsystem = "engine"
    if outcome in {"policy_rejected"}:
        subsystem = "policy"
    elif outcome in {"git_pr_lane_failed"}:
        subsystem = "git_tools"
    elif outcome in {"verification_failed"}:
        subsystem = "verification"
    elif outcome in {"advice_not_actionable"}:
        subsystem = "upgrade_advice"

    avoid_next_time = []
    if blocked_reason:
        avoid_next_time.append(blocked_reason)
    if outcome == "blocked_fake_noop":
        avoid_next_time.append("Do not mark success when patch_count=0 and patching was expected.")

    next_best_action = "Continue bounded repair with execution-target focus."
    if outcome == "advice_not_actionable":
        next_best_action = "Request actionable advice with concrete target files and patch strategy."
    elif outcome == "policy_rejected":
        next_best_action = "Generate policy-safe patch paths and bounded operations."
    elif outcome == "verification_failed":
        next_best_action = "Rollback and prioritize failing subsystem diagnostics."
    elif outcome == "clean_no_action":
        next_best_action = "Record no-action rationale and wait for actionable signal."

    return RunLearningLedgerEntry(
        run_id=record.run_id,
        selected_mode=str(record.selected_mode or ""),
        outcome=outcome,
        subsystem=subsystem,
        root_cause=sanitize_text(blocked_reason or str(getattr(record, "summary", "") or "")),
        why_it_happened=sanitize_text(str(getattr(record, "summary", "") or "")),
        what_worked=sanitize_list(what_worked),
        what_failed=sanitize_list(what_failed),
        files_involved=files,
        target_files=target_files,
        tests_run=tests_run,
        trace_events=sanitize_list(events[-25:]),
        patch_count=patch_count,
        attempted_patch_count=attempted_patch_count,
        successful_patch_count=patch_count,
        blocked_reason=sanitize_text(blocked_reason),
        next_best_action=sanitize_text(next_best_action),
        avoid_next_time=sanitize_list(avoid_next_time[:10]),
        confidence=0.8 if patch_count > 0 else 0.6,
        source=source,
    )
