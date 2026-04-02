from __future__ import annotations
from typing import Any, List, Dict
from collections import Counter

def summarize_trace(trace: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    """Generate concise summary for execution traces."""
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

def log_trace_summary(details: Any) -> None:
    """Append a trace summary to the log file."""
    with open("trace_summary.log", "a") as f:
        f.write(f"{details}\n")
