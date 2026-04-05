from __future__ import annotations

import json
import sys
from pathlib import Path

from .config import get_settings
from .core.upgrade_gate import UpgradeGateError, validate_upgrade_gate_for_settings
from .engine import DaddyEngine


def _json_default(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _print_run_summary(record) -> None:
    payload = {
        "run_id": getattr(record, "run_id", ""),
        "command": getattr(record, "command", ""),
        "selected_mode": getattr(record, "selected_mode", "unknown"),
        "success": getattr(record, "success", False),
        "summary": getattr(record, "summary", ""),
        "patch_count": len(getattr(record, "patches_applied", []) or []),
        "patches_applied": getattr(record, "patches_applied", []) or [],
        "rollback_manifest": getattr(record, "rollback_manifest", []) or [],
        "trace": getattr(record, "trace", []) or [],
        "backlog_updates": getattr(record, "backlog_updates", []) or [],
        "repo_fingerprint": getattr(record, "repo_fingerprint", {}) or {},
        "verification": getattr(record, "verification", None),
    }

    self_evolution = getattr(record, "self_evolution", None)
    if self_evolution is not None:
        payload["self_evolution"] = {
            "enabled": getattr(self_evolution, "enabled", False),
            "attempted": getattr(self_evolution, "attempted", False),
            "applied": getattr(self_evolution, "applied", False),
            "route": getattr(self_evolution, "route", ""),
            "summary": getattr(self_evolution, "summary", ""),
            "reasons": getattr(self_evolution, "reasons", []) or [],
            "proposed_count": getattr(self_evolution, "proposed_count", 0),
            "applied_count": getattr(self_evolution, "applied_count", 0),
            "patches": getattr(self_evolution, "patches", []) or [],
        }

    architecture_review = getattr(record, "architecture_review", None)
    if architecture_review is not None:
        payload["architecture_review"] = {
            "risk_level": getattr(architecture_review, "risk_level", ""),
            "self_evolution_actions": len(getattr(architecture_review, "self_evolution_actions", []) or []),
            "build_actions": len(getattr(architecture_review, "build_actions", []) or []),
            "architecture_plans": len(getattr(architecture_review, "architecture_plans", []) or []),
            "execution_notes": getattr(architecture_review, "execution_notes", []) or [],
            "backlog_items": getattr(architecture_review, "backlog_items", []) or [],
        }
        payload["proposed_self_evolution_actions"] = [
            {
                "title": getattr(action, "title", ""),
                "description": getattr(action, "description", ""),
                "risk": getattr(action, "risk", ""),
                "patch_paths": [
                    getattr(patch, "path", "")
                    for patch in getattr(action, "patches", []) or []
                ],
            }
            for action in getattr(architecture_review, "self_evolution_actions", []) or []
        ]

        plans = getattr(architecture_review, "architecture_plans", []) or []
        if plans:
            payload["architecture_plan_titles"] = [getattr(p, "title", "") for p in plans]
            payload["architecture_plan_patch_counts"] = [
                len(getattr(p, "patch_bundle", []) or []) for p in plans
            ]

    verification = getattr(record, "verification", None)
    if verification is not None:
        payload["verification_returncode"] = getattr(verification, "returncode", None)
        payload["verification_timed_out"] = getattr(verification, "timed_out", False)
        payload["verification_stdout"] = getattr(verification, "stdout", "") or ""
        payload["verification_stderr"] = getattr(verification, "stderr", "") or ""
        payload["verification_combined"] = getattr(verification, "combined", "") or ""

    print(json.dumps(payload, indent=2, default=_json_default))


def main() -> int:
    settings = get_settings()

    if len(sys.argv) < 2:
        print("Usage: python -m src.the_daddy.cli run", file=sys.stderr)
        return 2

    command = sys.argv[1].strip().lower()

    if command != "run":
        print(f"Unknown command: {command}", file=sys.stderr)
        return 2

    try:
        advice = validate_upgrade_gate_for_settings(settings)
    except UpgradeGateError as exc:
        print(f"Upgrade gate blocked execution: {exc}", file=sys.stderr)
        return 1

    if advice.get("repair_mode", False):
        print("Upgrade gate entered repair mode.", file=sys.stderr)

    engine = DaddyEngine(settings)
    engine.upgrade_advice = advice
    engine.repair_mode_active = bool(advice.get("repair_mode", False))

    try:
        record = engine.run()
    except UpgradeGateError as exc:
        print(f"Upgrade gate blocked engine execution: {exc}", file=sys.stderr)
        return 1

    _print_run_summary(record)

    return 0 if getattr(record, "success", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())