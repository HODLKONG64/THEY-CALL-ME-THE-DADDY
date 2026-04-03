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


def summarize_build_actions(actions: list[object] | None) -> list[str]:
    """Return compact human-readable summaries for proposed build actions."""
    if not actions:
        return []

    summaries: list[str] = []
    for action in actions:
        if isinstance(action, dict):
            work_id = str(action.get("work_id") or "unknown")
            title = str(action.get("title") or "untitled")
            state = str(action.get("state") or "unknown")
            priority = action.get("priority")
        else:
            work_id = str(getattr(action, "work_id", "unknown") or "unknown")
            title = str(getattr(action, "title", "untitled") or "untitled")
            state = str(getattr(action, "state", "unknown") or "unknown")
            priority = getattr(action, "priority", None)

        priority_label = "?" if priority is None else str(priority)
        summaries.append(f"{work_id} [p{priority_label}] {state}: {title}")

    return summaries



def summarize_build_action_titles(actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = actions or []
    titles = [str(item.get("title", "")).strip() for item in items if str(item.get("title", "")).strip()]
    return {
        "count": len(titles),
        "titles": titles[:10],
        "first_title": titles[0] if titles else "",
    }
