from __future__ import annotations

from typing import Any


def summarize_run_health(runs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = runs or []
    total_runs = len(items)
    success_count = 0
    failure_count = 0
    latest_run = items[-1] if items else None

    recent_modes: dict[str, int] = {}
    for item in items[-10:]:
        if bool(item.get("success", False)):
            success_count += 1
        else:
            failure_count += 1

        mode = str(item.get("selected_mode", "unknown")).strip() or "unknown"
        recent_modes[mode] = recent_modes.get(mode, 0) + 1

    success_rate = 0.0
    if total_runs > 0:
        success_rate = round(success_count / total_runs, 4)

    return {
        "total_runs": total_runs,
        "success_count": success_count,
        "failure_count": failure_count,
        "success_rate": success_rate,
        "recent_mode_counts": recent_modes,
        "latest_run": latest_run,
    }



def summarize_run_velocity(runs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = runs or []
    sample = items[-5:]
    success_count = sum(1 for item in sample if bool(item.get("success", False)))
    failure_count = len(sample) - success_count
    return {
        "sample_size": len(sample),
        "successes": success_count,
        "failures": failure_count,
    }



def summarize_mode_distribution(runs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = runs or []
    counts: dict[str, int] = {}

    for item in items[-20:]:
        mode = str(item.get("selected_mode", "unknown")).strip() or "unknown"
        counts[mode] = counts.get(mode, 0) + 1

    return {
        "sample_size": min(len(items), 20),
        "mode_counts": counts,
        "distinct_modes": len(counts),
    }
