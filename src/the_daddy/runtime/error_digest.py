from __future__ import annotations

from collections import Counter
from typing import Any


def summarize_errors(events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = events or []
    kinds = Counter()
    recent: list[dict[str, Any]] = []

    for item in items:
        event = str(item.get("event", "unknown")).strip() or "unknown"
        if event in {"patch_apply_failed", "pr_delivery_failed", "branch_prepare_failed"}:
            kinds[event] += 1
            if len(recent) < 5:
                recent.append(item)

    return {
        "total_error_events": sum(kinds.values()),
        "error_counts": dict(kinds),
        "recent_errors": recent,
    }



def summarize_traceback_excerpt(text: str, max_lines: int = 12) -> dict[str, Any]:
    lines = [line.rstrip() for line in str(text or "").splitlines() if line.strip()]
    tail = lines[-max_lines:]
    return {
        "line_count": len(lines),
        "excerpt": tail,
        "last_line": tail[-1] if tail else "",
    }
