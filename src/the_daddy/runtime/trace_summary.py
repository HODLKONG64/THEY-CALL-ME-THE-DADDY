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



def summarize_recent_build_action_pressure(runs: list[object], window: int = 6) -> dict[str, int | bool]:
    """Return a compact summary of recent build-action pressure from run traces."""
    recent_runs = list(runs[-max(1, int(window)):]) if runs else []
    summary_count = 0
    pressured_runs = 0

    for run in recent_runs:
        trace = getattr(run, "trace", None)
        if trace is None and isinstance(run, dict):
            trace = run.get("trace", [])
        if not isinstance(trace, list):
            continue

        found_pressure = False
        for event in trace:
            if not isinstance(event, dict):
                continue
            if event.get("event") != "runtime_build_action_summary":
                continue
            summary = event.get("summary")
            if not isinstance(summary, dict):
                continue
            count = int(summary.get("count", 0) or 0)
            summary_count += count
            if count > 0:
                found_pressure = True
        if found_pressure:
            pressured_runs += 1

    return {
        "window": len(recent_runs),
        "build_action_count": summary_count,
        "pressured_runs": pressured_runs,
        "has_pressure": summary_count > 0,
    }
