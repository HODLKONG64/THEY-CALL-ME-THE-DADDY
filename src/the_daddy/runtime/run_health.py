from __future__ import annotations

from typing import Any


RECENT_HEALTH_WINDOW = 10
RECENT_VELOCITY_WINDOW = 5


def summarize_run_health(
    runs: list[dict[str, Any]] | None = None,
    window: int = RECENT_HEALTH_WINDOW,
) -> dict[str, Any]:
    items = runs or []
    total_runs = len(items)
    latest_run = items[-1] if items else None

    effective_window = max(1, int(window))
    sample = items[-effective_window:] if items else []

    success_count = sum(1 for item in sample if bool(item.get("success", False)))
    failure_count = len(sample) - success_count

    recent_modes: dict[str, int] = {}
    for item in sample:
        mode = str(item.get("selected_mode", "unknown")).strip() or "unknown"
        recent_modes[mode] = recent_modes.get(mode, 0) + 1

    sample_size = len(sample)
    success_rate = round(success_count / sample_size, 4) if sample_size > 0 else 0.0

    return {
        "total_runs": total_runs,
        "sample_size": sample_size,
        "window": effective_window,
        "success_count": success_count,
        "failure_count": failure_count,
        "success_rate": success_rate,
        "recent_mode_counts": recent_modes,
        "latest_run": latest_run,
    }


def summarize_run_velocity(
    runs: list[dict[str, Any]] | None = None,
    window: int = RECENT_VELOCITY_WINDOW,
) -> dict[str, Any]:
    items = runs or []
    effective_window = max(1, int(window))
    sample = items[-effective_window:] if items else []

    success_count = sum(1 for item in sample if bool(item.get("success", False)))
    failure_count = len(sample) - success_count

    return {
        "sample_size": len(sample),
        "window": effective_window,
        "successes": success_count,
        "failures": failure_count,
    }


def summarize_mode_distribution(
    runs: list[dict[str, Any]] | None = None,
    window: int = 20,
) -> dict[str, Any]:
    items = runs or []
    effective_window = max(1, int(window))
    sample = items[-effective_window:] if items else []
    counts: dict[str, int] = {}

    for item in sample:
        mode = str(item.get("selected_mode", "unknown")).strip() or "unknown"
        counts[mode] = counts.get(mode, 0) + 1

    return {
        "sample_size": len(sample),
        "window": effective_window,
        "mode_counts": counts,
        "distinct_modes": len(counts),
    }
