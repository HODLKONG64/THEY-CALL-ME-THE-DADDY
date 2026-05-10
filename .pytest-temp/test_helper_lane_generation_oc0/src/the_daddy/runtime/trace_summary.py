from __future__ import annotations

from typing import Any

def summarize_trace(trace):
    return {}


def summarize_noop_repair_state(run_payload: dict) -> dict:
    return {
        "repair_noop": bool(run_payload.get("summary") == "No safe repair patch available"),
        "patch_count": int(run_payload.get("patch_count", 0) or 0),
        "success": bool(run_payload.get("success", False)),
    }
