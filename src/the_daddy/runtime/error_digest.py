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


def summarize_error_paths(events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = events or []
    paths: dict[str, int] = {}

    for item in items:
        path = str(item.get("path", "")).strip()
        if not path:
            continue
        paths[path] = paths.get(path, 0) + 1

    ranked = sorted(paths.items(), key=lambda item: (-item[1], item[0]))
    return {
        "path_count": len(paths),
        "top_paths": ranked[:10],
        "first_path": ranked[0][0] if ranked else "",
    }


def summarize_error_messages(events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = events or []
    counts: dict[str, int] = {}

    for item in items:
        message = str(item.get("error", "")).strip()
        if not message:
            continue
        counts[message] = counts.get(message, 0) + 1

    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return {
        "message_count": len(counts),
        "top_messages": ranked[:10],
        "first_message": ranked[0][0] if ranked else "",
    }


def summarize_error_event_kinds(events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = events or []
    counts: dict[str, int] = {}

    for item in items:
        event = str(item.get("event", "")).strip()
        if not event:
            continue
        counts[event] = counts.get(event, 0) + 1

    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return {
        "kind_count": len(counts),
        "top_kinds": ranked[:10],
        "first_kind": ranked[0][0] if ranked else "",
    }
