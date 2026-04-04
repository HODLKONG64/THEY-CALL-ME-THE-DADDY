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


def summarize_build_actions(actions: list[object] | None = None) -> dict[str, Any]:
    items = actions or []
    normalized: list[str] = []

    for item in items:
        if isinstance(item, dict):
            title = str(item.get("title", "")).strip()
        else:
            title = str(getattr(item, "title", "")).strip()
        if title:
            normalized.append(title)

    return {
        "count": len(normalized),
        "titles": normalized[:10],
        "first_title": normalized[0] if normalized else "",
    }


def summarize_build_action_titles(actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = actions or []
    titles = [str(item.get("title", "")).strip() for item in items if str(item.get("title", "")).strip()]
    return {
        "count": len(titles),
        "titles": titles[:10],
        "first_title": titles[0] if titles else "",
    }


def summarize_build_action_pressure(actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = actions or []
    titles = [str(item.get("title", "")).strip() for item in items if str(item.get("title", "")).strip()]
    notes: list[str] = []
    related_files: list[str] = []

    for item in items:
        for note in item.get("notes", []) or []:
            note_text = str(note).strip()
            if note_text:
                notes.append(note_text)
        for path in item.get("related_files", []) or []:
            path_text = str(path).strip()
            if path_text:
                related_files.append(path_text)

    unique_files = list(dict.fromkeys(related_files))
    unique_notes = list(dict.fromkeys(notes))
    pressure_score = len(titles) + len(unique_files)

    return {
        "count": len(titles),
        "titles": titles[:10],
        "first_title": titles[0] if titles else "",
        "related_files_count": len(unique_files),
        "related_files": unique_files[:10],
        "notes_count": len(unique_notes),
        "pressure_score": pressure_score,
        "active": pressure_score > 0,
    }


def summarize_build_pressure_paths(actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = actions or []
    paths: dict[str, int] = {}

    for item in items:
        for path in item.get("related_files", []) or []:
            path_text = str(path).strip()
            if not path_text:
                continue
            paths[path_text] = paths.get(path_text, 0) + 1

    ranked = sorted(paths.items(), key=lambda item: (-item[1], item[0]))
    return {
        "path_count": len(paths),
        "top_paths": ranked[:10],
        "first_path": ranked[0][0] if ranked else "",
    }

def summarize_build_pressure_source(build_pressure_summary: dict | None, build_action_summary: dict | None) -> dict[str, object]:
    """Return a tiny normalized view of build-pressure provenance."""
    pressure_summary = build_pressure_summary if isinstance(build_pressure_summary, dict) else {}
    action_summary = build_action_summary if isinstance(build_action_summary, dict) else {}

    if pressure_summary:
        pressure_score = int(pressure_summary.get("pressure_score", 0) or 0)
        active = bool(pressure_summary.get("active", False))
        return {
            "source": "build_pressure_summary",
            "pressure_score": pressure_score,
            "active": active,
        }

    fallback_count = int(action_summary.get("count", 0) or 0)
    if fallback_count > 0:
        return {
            "source": "build_action_summary_fallback",
            "pressure_score": fallback_count,
            "active": True,
        }

    return {
        "source": "none",
        "pressure_score": 0,
        "active": False,
    }
