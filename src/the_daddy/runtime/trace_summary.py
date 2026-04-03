from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TRACE_SUMMARY_LOG = Path("trace_summary.log")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def summarize_trace(trace: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Generate a stable summary for execution traces."""
    items = trace or []
    counts: Counter[str] = Counter()

    for item in items:
        event = str(item.get("event", "unknown")).strip() or "unknown"
        counts[event] += 1

    return {
        "generated_at": _utc_now_iso(),
        "total_events": len(items),
        "event_counts": dict(counts),
        "first_event": items[0] if items else None,
        "last_event": items[-1] if items else None,
    }


def format_trace_summary(trace: list[dict[str, Any]] | None = None) -> str:
    """Return a readable JSON string for the trace summary."""
    summary = summarize_trace(trace)
    return json.dumps(summary, ensure_ascii=False, sort_keys=True)


def log_trace_summary(details: Any) -> None:
    """Append a trace summary or arbitrary details to the log file."""
    TRACE_SUMMARY_LOG.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(details, list):
        payload = format_trace_summary(details)
    elif isinstance(details, dict):
        payload = json.dumps(details, ensure_ascii=False, sort_keys=True)
    else:
        payload = str(details)

    with TRACE_SUMMARY_LOG.open("a", encoding="utf-8") as handle:
        handle.write(payload)
        handle.write("\n")
