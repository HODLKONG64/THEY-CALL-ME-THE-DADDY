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
