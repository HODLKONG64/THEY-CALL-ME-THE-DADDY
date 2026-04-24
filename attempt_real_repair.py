#!/usr/bin/env python3
"""attempt_real_repair.py — Phase 2 stability repair entry-point.

Implements the exact Phase 2 decision sequence from decision_contract.json
and validates all items in phase2_stability_checklist.json.

Decision sequence (decision_contract.json):
  Step 1  grounded_patch_attempt          – try a grounded bounded patch first
  Step 2  safe_helper_lane_attempt        – if none, try safe helper-lane improvement
  Step 3  deadlock_diagnosis              – if no patch, record why in trace
  Step 4  extreme_pressure_check          – evaluate pressure metrics
  Step 5  forced_safe_creation_or_extension – under extreme pressure, force safe
                                             action from allowed_targets_order
                                             BEFORE any default build action
  Step 6  default_build_action_last       – default build is last resort only

Phase 2 checklist (phase2_stability_checklist.json):
  1. reviewer_does_not_return_early_under_extreme_pressure
  2. engine_does_not_default_to_build_action_before_forced_safe_extension_check
  3. no_silent_noop_runs_when_pressure_score_gte_7_and_runs_without_patches_gte_7
  4. pr_flow_recovers_after_no_action_runs
  5. rollback_path_remains_intact
  6. core_files_are_protected_from_shrink_or_replace

Usage:
    python attempt_real_repair.py [--dry-run] [--skip-recheck] [--skip-checklist]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

# ---------------------------------------------------------------------------
# Contract / checklist loading
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_decision_contract() -> dict[str, Any]:
    return _load_json(ROOT / "decision_contract.json")


def _load_phase2_checklist() -> dict[str, Any]:
    return _load_json(ROOT / "phase2_stability_checklist.json")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def _run_tests(label: str = "tests") -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=short"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    output = (result.stdout or "") + (result.stderr or "")
    print(f"--- {label} ---")
    print(output.rstrip())
    print(f"--- returncode: {result.returncode} ---")
    return result.returncode, output


# ---------------------------------------------------------------------------
# src-layout import helper
# ---------------------------------------------------------------------------

def _ensure_src_importable() -> None:
    src_str = str(SRC)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)


# ---------------------------------------------------------------------------
# Phase 2 pressure evaluation (Step 4)
# ---------------------------------------------------------------------------

EXTREME_PRESSURE_METRICS = {
    "pressure_score_gte": 7,
    "runs_without_patches_gte": 7,
    "average_patch_count_lte": 0.2,
    "success_rate_gte": 0.85,
}


def _evaluate_extreme_pressure(memory_state: Any) -> dict[str, Any]:
    """Evaluate whether extreme pressure conditions are met (Step 4).

    Uses the ImprovementPlanner's built-in pressure escalation logic so the
    evaluation is always consistent with how the engine itself decides.
    """
    _ensure_src_importable()
    from the_daddy.agents.improvement_planner import ImprovementPlanner  # noqa: PLC0415

    planner = ImprovementPlanner()
    decision = planner.summarize_pressure_escalation_decision(memory_state)

    # Cross-check against the contract's numeric thresholds.
    contract_qualifies = (
        int(decision.get("build_pressure_score", 0) or 0) >= EXTREME_PRESSURE_METRICS["pressure_score_gte"]
        and int(decision.get("no_patch_streak", 0) or 0) >= EXTREME_PRESSURE_METRICS["runs_without_patches_gte"]
        and float(decision.get("average_patch_count", 1.0) or 1.0) <= EXTREME_PRESSURE_METRICS["average_patch_count_lte"]
        and float(decision.get("success_rate", 0.0) or 0.0) >= EXTREME_PRESSURE_METRICS["success_rate_gte"]
    )

    return {
        "planner_force_deeper_action": bool(decision.get("force_deeper_action", False)),
        "contract_qualifies": contract_qualifies,
        "extreme_pressure_active": bool(decision.get("force_deeper_action", False)) or contract_qualifies,
        "metrics": decision,
    }


# ---------------------------------------------------------------------------
# Phase 2 decision sequence (Steps 1-6)
# ---------------------------------------------------------------------------

def _run_phase2_engine() -> dict[str, Any]:
    """Run DaddyEngine following the Phase 2 decision sequence.

    Returns a rich result dict including the full trace and Phase 2 step log.
    """
    _ensure_src_importable()
    from the_daddy.config import Settings  # noqa: PLC0415
    from the_daddy.engine import DaddyEngine  # noqa: PLC0415

    settings = Settings()
    engine = DaddyEngine(settings)

    # Evaluate pressure state BEFORE invoking the engine (Step 4 pre-check).
    memory_state = engine.memory.state
    pressure = _evaluate_extreme_pressure(memory_state)

    step_log: list[dict[str, Any]] = []

    # Step 4 — log pressure evaluation result.
    step_log.append({
        "step": 4,
        "name": "extreme_pressure_check",
        "extreme_pressure_active": pressure["extreme_pressure_active"],
        "contract_qualifies": pressure["contract_qualifies"],
        "planner_force_deeper_action": pressure["planner_force_deeper_action"],
        "metrics": pressure["metrics"],
    })

    if pressure["extreme_pressure_active"]:
        # Step 5 — under extreme pressure, engine MUST attempt forced safe
        # creation/extension from the contract's allowed_targets_order before
        # any default build action.  This is enforced inside the engine itself
        # (_build_forced_target_patches / _doctor_takeover_patches), but we
        # record it here so the trace validator can verify.
        step_log.append({
            "step": 5,
            "name": "forced_safe_creation_or_extension",
            "triggered": True,
            "reason": "extreme_pressure_active — engine must force safe target before default build",
        })
    else:
        # Step 6 — no extreme pressure; default build action is the last resort.
        step_log.append({
            "step": 6,
            "name": "default_build_action_last",
            "triggered": True,
            "reason": "extreme_pressure_not_active — default build action permitted",
        })

    # Invoke the engine (which internally follows Steps 1-3 and 5/6 via its
    # grounded patch → helper lane → forced fallback → doctor takeover path).
    record = engine.run()

    trace = list(getattr(record, "trace", []) or [])
    patches_applied = list(getattr(record, "patches_applied", []) or [])

    # Step 1 — grounded patch attempt: check whether a non-heartbeat patch was proposed.
    grounded_actions = [
        e for e in trace
        if e.get("event") == "proposed_actions"
        and any(a.get("patch_paths") for a in (e.get("actions") or []))
    ]
    step_log.append({
        "step": 1,
        "name": "grounded_patch_attempt",
        "grounded_actions_found": bool(grounded_actions),
    })

    # Step 2 — safe helper-lane attempt.
    helper_injected = any(
        "helper injection" in str(e).lower() or "helper override" in str(e).lower()
        for e in trace
    )
    step_log.append({
        "step": 2,
        "name": "safe_helper_lane_attempt",
        "helper_lane_used": helper_injected,
    })

    # Step 3 — deadlock diagnosis: was a no-patch state recorded in the trace?
    deadlock_recorded = any(
        e.get("event") in {
            "repair_mode_no_patches_remaining",
            "repair_mode_no_patches_generated",
            "repair_mode_no_target_match",
            "patch_blocked_by_depth_learning",
        }
        for e in trace
    )
    step_log.append({
        "step": 3,
        "name": "deadlock_diagnosis",
        "deadlock_recorded": deadlock_recorded,
        "no_patches_emitted": len(patches_applied) == 0,
    })

    return {
        "run_id": getattr(record, "run_id", ""),
        "success": bool(getattr(record, "success", False)),
        "summary": str(getattr(record, "summary", "")),
        "selected_mode": str(getattr(record, "selected_mode", "")),
        "patch_count": len(patches_applied),
        "changed_files": [
            p.get("path", "") if isinstance(p, dict) else getattr(p, "path", "")
            for p in patches_applied
        ],
        "trace": trace,
        "pressure": pressure,
        "step_log": step_log,
        "record": record,
    }


# ---------------------------------------------------------------------------
# Phase 2 checklist validation
# ---------------------------------------------------------------------------

_CORE_FILES = {
    "src/the_daddy/engine.py",
    "src/the_daddy/agents/reviewer.py",
    "src/the_daddy/agents/improvement_planner.py",
    "src/the_daddy/memory/repository.py",
    "src/the_daddy/core/system_rules.json",
    "src/the_daddy/core/self_check.py",
    "src/the_daddy/core/conflict_recovery.py",
    "src/the_daddy/core/failure_recovery.py",
}


def _check_checklist(engine_result: dict[str, Any]) -> dict[str, bool]:
    """Evaluate all 6 Phase 2 checklist items against the engine run record."""
    trace: list[dict[str, Any]] = engine_result.get("trace", [])
    pressure: dict[str, Any] = engine_result.get("pressure", {})
    patch_count: int = engine_result.get("patch_count", 0)
    changed_files: list[str] = engine_result.get("changed_files", [])
    record = engine_result.get("record")

    # 1. reviewer_does_not_return_early_under_extreme_pressure
    #    Pass when: extreme pressure was NOT active, OR when it was active and the
    #    engine still emitted at least one patch (forced or grounded).
    extreme_active = bool(pressure.get("extreme_pressure_active", False))
    item1 = (not extreme_active) or (extreme_active and patch_count > 0)

    # 2. engine_does_not_default_to_build_action_before_forced_safe_extension_check
    #    Pass when: forced_target_patch_generation_skipped event is NOT present
    #    UNLESS it was preceded by a forced_target_patch_generated event, OR when
    #    the engine correctly resolved the forced path.
    forced_generated = any(e.get("event") == "forced_target_patch_generated" for e in trace)
    forced_skipped_without_generation = any(
        e.get("event") == "forced_target_patch_generation_skipped" for e in trace
    ) and not forced_generated
    # Also pass if no extreme pressure, meaning the step was not applicable.
    item2 = (not extreme_active) or forced_generated or (not forced_skipped_without_generation)

    # 3. no_silent_noop_runs_when_pressure_score_gte_7_and_runs_without_patches_gte_7
    #    Pass when: if extreme pressure is active, patch_count > 0 OR a deadlock
    #    diagnosis was explicitly recorded (silent no-op is the failure case).
    deadlock_recorded = any(
        e.get("event") in {
            "repair_mode_no_patches_remaining",
            "repair_mode_no_patches_generated",
            "repair_mode_no_target_match",
            "patch_blocked_by_depth_learning",
        }
        for e in trace
    )
    item3 = (not extreme_active) or (patch_count > 0) or deadlock_recorded

    # 4. pr_flow_recovers_after_no_action_runs
    #    Pass when: PR lane was attempted (pr_opened, pr_left_open, or pr_skipped
    #    with a known non-patch reason) OR patches were applied successfully.
    pr_events = {e.get("event") for e in trace}
    pr_lane_active = bool(
        pr_events & {"pr_opened", "pr_left_open", "pr_merged"}
        or (patch_count > 0)
    )
    item4 = pr_lane_active or bool(engine_result.get("success"))

    # 5. rollback_path_remains_intact
    #    Pass when: rollback manifest is present on the record (it is always built,
    #    even if empty), confirming the rollback path is structurally intact.
    rollback_manifest = getattr(record, "rollback_manifest", None) if record else None
    item5 = rollback_manifest is not None  # empty list is fine; None means broken

    # 6. core_files_are_protected_from_shrink_or_replace
    #    Pass when: no patch applied to a core-protected file used replace_file or
    #    shrank the file.
    def _patch_path(p: Any) -> str:
        return p.get("path", "") if isinstance(p, dict) else getattr(p, "path", "")

    patches_applied = list(getattr(record, "patches_applied", []) or []) if record else []
    item6 = True
    for p in patches_applied:
        path = _patch_path(p)
        if path in _CORE_FILES:
            before = int(p.get("bytes_before", 0) if isinstance(p, dict) else getattr(p, "bytes_before", 0))
            after = int(p.get("bytes_after", 0) if isinstance(p, dict) else getattr(p, "bytes_after", 0))
            op = p.get("operation", "") if isinstance(p, dict) else getattr(p, "operation", "")
            if op == "replace_file" or (after > 0 and after < before):
                item6 = False
                break

    return {
        "reviewer_does_not_return_early_under_extreme_pressure": item1,
        "engine_does_not_default_to_build_action_before_forced_safe_extension_check": item2,
        "no_silent_noop_runs_when_pressure_score_gte_7_and_runs_without_patches_gte_7": item3,
        "pr_flow_recovers_after_no_action_runs": item4,
        "rollback_path_remains_intact": item5,
        "core_files_are_protected_from_shrink_or_replace": item6,
    }


def _report_checklist(results: dict[str, bool]) -> bool:
    """Print checklist results and return True if all items pass."""
    print("\n--- Phase 2 checklist ---")
    all_pass = True
    for item, passed in results.items():
        mark = "✓" if passed else "✗"
        print(f"  {mark} {item}")
        if not passed:
            all_pass = False
    return all_pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 2 stability repair: follows the exact Phase 2 decision contract."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run verification only; do not invoke the engine.",
    )
    parser.add_argument(
        "--skip-recheck",
        action="store_true",
        help="Skip the post-repair test re-run.",
    )
    parser.add_argument(
        "--skip-checklist",
        action="store_true",
        help="Skip Phase 2 checklist validation (does not affect exit code from tests).",
    )
    args = parser.parse_args()

    contract = _load_decision_contract()
    checklist = _load_phase2_checklist()

    print("=" * 60)
    print("attempt_real_repair — Phase 2 stability spec")
    print(f"  contract version : {contract.get('version', 'unknown')}")
    print(f"  contract purpose : {contract.get('purpose', 'unknown')}")
    print(f"  checklist phase  : {checklist.get('phase', 'unknown')}")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Step 0 — pre-repair verification
    # ------------------------------------------------------------------
    print("\n[Step 0] Pre-repair verification (pytest -q)")
    rc_pre, _ = _run_tests("pre-repair")

    if rc_pre == 0 and args.dry_run:
        print("\n✓ Tests pass and --dry-run set — nothing to repair.")
        return 0

    if rc_pre == 0:
        print("\n✓ Tests pass — checking Phase 2 stability state ...")
    else:
        print(f"\n✗ Tests failed (rc={rc_pre}) — invoking Phase 2 repair cycle.")

    if args.dry_run:
        print("--dry-run: skipping engine invocation.")
        return 0 if rc_pre == 0 else 1

    # ------------------------------------------------------------------
    # Steps 1-6 — Phase 2 decision sequence via DaddyEngine
    # ------------------------------------------------------------------
    print("\n[Steps 1–6] Phase 2 decision sequence")
    try:
        engine_result = _run_phase2_engine()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Phase 2 engine cycle failed: {exc}", file=sys.stderr)
        return 1

    print("\nPhase 2 step log:")
    for entry in engine_result.get("step_log", []):
        step_num = entry.get("step", "?")
        name = entry.get("name", "")
        details = {k: v for k, v in entry.items() if k not in ("step", "name")}
        print(f"  Step {step_num} [{name}]: {json.dumps(details)}")

    print(f"\nEngine result: success={engine_result['success']} "
          f"patches={engine_result['patch_count']} "
          f"mode={engine_result['selected_mode']}")
    if engine_result["changed_files"]:
        print(f"  changed files: {engine_result['changed_files']}")
    if not engine_result["success"]:
        print(f"  summary: {engine_result['summary']}")

    # ------------------------------------------------------------------
    # Post-repair verification
    # ------------------------------------------------------------------
    if not args.skip_recheck:
        print("\n[Post-repair] Re-running verification")
        rc_post, _ = _run_tests("post-repair")
        verification_passed = rc_post == 0
        if verification_passed:
            print("\n✓ Post-repair verification passed.")
        else:
            print(f"\n✗ Post-repair verification failed (rc={rc_post}).")
    else:
        verification_passed = engine_result["success"]

    # ------------------------------------------------------------------
    # Phase 2 checklist validation
    # ------------------------------------------------------------------
    if not args.skip_checklist:
        checklist_results = _check_checklist(engine_result)
        checklist_passed = _report_checklist(checklist_results)

        done_when = checklist.get("done_when", [])
        done_status = {
            "at_least_one_real_bounded_patch_is_emitted_after_deadlock_state": engine_result["patch_count"] > 0,
            "tests_pass": verification_passed,
            "pr_is_opened": any(
                e.get("event") in {"pr_opened", "pr_merged"}
                for e in engine_result.get("trace", [])
            ),
            "safe_merge_is_possible": bool(engine_result.get("success")),
        }
        print("\n--- Phase 2 done-when ---")
        for item in done_when:
            val = done_status.get(item)
            mark = "✓" if val else "✗"
            print(f"  {mark} {item}")

        phase2_done = all(done_status.get(item, False) for item in done_when)
        if phase2_done:
            print("\n✓ Phase 2 complete — all done-when criteria satisfied.")
        else:
            print("\n  Phase 2 not yet complete — see done-when results above.")
    else:
        checklist_passed = True

    # Exit 0 only when tests pass AND all checklist items pass.
    if verification_passed and checklist_passed:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
