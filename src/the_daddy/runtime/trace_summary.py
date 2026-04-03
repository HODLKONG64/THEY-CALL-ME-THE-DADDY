from __future__ import annotations

from collections import Counter
from typing import Any


def summarize_trace(trace: list[dict[str, Any]] | None) -> dict[str, Any]:
    items = trace or []
    counts = Counter()

    for item in items:
        event = str(item.get("event", "unknown")).strip() or "unknown"
        counts[event] += 1

    return {
        "total_events": len(items),
        "event_counts": dict(counts),
        "last_event": items[-1] if items else None,
    }



def summarize_self_evolution_skips(reasons: list[str] | None = None) -> dict[str, Any]:
    items = [str(item).strip() for item in (reasons or []) if str(item).strip()]
    blocked = [item for item in items if item.lower().startswith("blocked ")]
    return {
        "total_reasons": len(items),
        "blocked_count": len(blocked),
        "blocked_reasons": blocked,
        "all_reasons": items,
    }
