from __future__ import annotations

from typing import Any

RECENT_VELOCITY_WINDOW = 10


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
    noop_count = sum(1 for r in items if str(r.get("summary", "")).startswith("No safe repair"))
    return {
        "noop_repair_count": noop_count,
        "total_runs": len(items),
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
