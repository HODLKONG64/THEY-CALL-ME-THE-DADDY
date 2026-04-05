from __future__ import annotations

from typing import Any


RECENT_HEALTH_WINDOW = 10
RECENT_VELOCITY_WINDOW = 5
RECENT_PATCH_VELOCITY_WINDOW = 8


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


def summarize_patch_velocity(
    runs: list[dict[str, Any]] | None = None,
    window: int = RECENT_PATCH_VELOCITY_WINDOW,
) -> dict[str, Any]:
    items = runs or []
    effective_window = max(1, int(window))
    sample = items[-effective_window:] if items else []

    patch_counts = [int(item.get("patch_count", 0) or 0) for item in sample]
    runs_with_patches = sum(1 for count in patch_counts if count > 0)
    runs_without_patches = len(sample) - runs_with_patches
    total_patches = sum(patch_counts)
    max_patch_count = max(patch_counts) if patch_counts else 0
    average_patch_count = round(total_patches / len(sample), 4) if sample else 0.0

    return {
        "sample_size": len(sample),
        "window": effective_window,
        "runs_with_patches": runs_with_patches,
        "runs_without_patches": runs_without_patches,
        "total_patches": total_patches,
        "max_patch_count": max_patch_count,
        "average_patch_count": average_patch_count,
    }


def summarize_patchless_streak(runs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = runs or []
    streak = 0

    for item in reversed(items):
        patch_count = int(item.get("patch_count", 0) or 0)
        if patch_count > 0:
            break
        streak += 1

    latest_mode = ""
    if items:
        latest_mode = str(items[-1].get("selected_mode", "")).strip()

    return {
        "patchless_streak": streak,
        "total_runs": len(items),
        "latest_mode": latest_mode,
        "active": streak > 0,
    }


def summarize_recent_patch_mix(
    runs: list[dict[str, Any]] | None = None,
    window: int = 10,
) -> dict[str, Any]:
    items = (runs or [])[-max(1, int(window)):]
    patch_counts = [int(item.get("patch_count", 0) or 0) for item in items]

    return {
        "sample_size": len(items),
        "patched_runs": sum(1 for count in patch_counts if count > 0),
        "patchless_runs": sum(1 for count in patch_counts if count == 0),
        "total_patches": sum(patch_counts),
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
