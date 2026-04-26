from __future__ import annotations

from typing import Any


def summarize_run_health(
    runs: list[dict[str, Any]] | None = None,
    window: int = 10,
) -> dict[str, Any]:
    items = runs or []
    sample = items[-max(1, int(window)):] if items else []

    success_count = sum(1 for item in sample if bool(item.get("success", False)))
    failure_count = len(sample) - success_count

    return {
        "total_runs": len(items),
        "sample_size": len(sample),
        "window": window,
        "success_count": success_count,
        "failure_count": failure_count,
        "success_rate": (success_count / len(sample)) if sample else 0.0,
        "recent_mode_counts": {
            item.get("selected_mode", "unknown"): sum(
                1 for r in sample if r.get("selected_mode") == item.get("selected_mode")
            )
            for item in sample
        },
        "latest_run": sample[-1] if sample else {},
    }


def recovery_tick_marker() -> dict[str, Any]:
    return {
        "status": "recovery_tick",
        "source": "forced_safe_recovery_patch",
    }


def recovery_tick_marker_v2() -> dict[str, Any]:
    return {
        "status": "recovery_tick",
        "source": "forced_safe_recovery_patch",
    }


def summarize_repair_noop_ticks(runs: list[dict] | None = None) -> dict:
    items = runs or []
    noop_count = sum(
        1 for r in items
        if str(r.get("summary", "")).startswith("No safe repair")
    )
    return {
        "noop_repair_count": noop_count,
        "total_runs": len(items),
    }
