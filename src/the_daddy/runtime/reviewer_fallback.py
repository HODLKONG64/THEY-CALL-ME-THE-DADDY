from __future__ import annotations

from typing import Any


def fallback_review_summary(reason: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(details or {})
    payload["reason"] = reason
    payload["source"] = "wake_reviewer_fallback"
    return payload


def summarize_fallback_reason_counts(reasons: list[str] | None = None) -> dict[str, Any]:
    items = [str(item).strip() for item in (reasons or []) if str(item).strip()]
    counts: dict[str, int] = {}

    for item in items:
        counts[item] = counts.get(item, 0) + 1

    return {
        "reason_count": len(items),
        "unique_reasons": len(counts),
        "counts": counts,
    }


def summarize_fallback_lane_status(
    reasons: list[str] | None = None,
    build_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    items = [str(item).strip() for item in (reasons or []) if str(item).strip()]
    actions = build_actions or []
    titles = [str(item.get("title", "")).strip() for item in actions if str(item.get("title", "")).strip()]
    helper_paths: list[str] = []

    for item in actions:
        for path in item.get("related_files", []) or []:
            path_text = str(path).strip()
            if path_text and path_text not in helper_paths:
                helper_paths.append(path_text)

    return {
        "reason_count": len(items),
        "build_action_count": len(titles),
        "first_build_action": titles[0] if titles else "",
        "helper_targets": helper_paths[:10],
        "has_pressure": bool(titles) or bool(helper_paths),
    }


def summarize_fallback_pressure_targets(build_actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = build_actions or []
    targets: list[str] = []

    for item in items:
        for path in item.get("related_files", []) or []:
            path_text = str(path).strip()
            if path_text and path_text not in targets:
                targets.append(path_text)

    return {
        "target_count": len(targets),
        "targets": targets[:10],
        "first_target": targets[0] if targets else "",
    }
