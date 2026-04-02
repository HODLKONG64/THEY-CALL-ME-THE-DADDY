from __future__ import annotations

from collections import Counter
from typing import Any


def summarize_errors(events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = events or []
    counts = Counter()
    recent: list[dict[str, Any]] = []

    for item in items:
        event = str(item.get("event", "unknown")).strip() or "unknown"
        if event in {"patch_apply_failed", "pr_delivery_failed", "branch_prepare_failed", "run_failure"}:
            counts[event] += 1
            if len(recent) < 5:
                recent.append(item)

    return {
        "total_error_events": sum(counts.values()),
        "error_counts": dict(counts),
        "recent_errors": recent,
    }
