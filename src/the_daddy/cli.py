from __future__ import annotations

import json
import os
import sys

from .config import Settings
from .engine import DaddyEngine


def get_settings() -> Settings:
    return Settings()


def _load_advice():
    path = os.environ.get("DADDY_UPGRADE_ADVICE_PATH")
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _safe(obj):
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return str(obj)


def main() -> int:
    settings = get_settings()

    advice = _load_advice()

    if advice is None:
        print("Upgrade gate blocked execution: missing approved advice.", file=sys.stderr)
        return 1

    if not advice.get("allow_proceed", False):
        if str(advice.get("problem_type", "")).lower() != "healthy_safe_loop":
            print("Upgrade gate blocked execution: advice rejected.", file=sys.stderr)
            return 1

    engine = DaddyEngine(settings)
    record = engine.run()

    print(json.dumps({
        "run_id": getattr(record, "run_id", ""),
        "command": getattr(record, "command", ""),
        "selected_mode": getattr(record, "selected_mode", ""),
        "success": getattr(record, "success", False),
        "summary": getattr(record, "summary", ""),
        "patch_count": len(getattr(record, "patches_applied", [])),
        "patches_applied": getattr(record, "patches_applied", []),
        "rollback_manifest": getattr(record, "rollback_manifest", []),
        "trace": getattr(record, "trace", []),
        "backlog_updates": getattr(record, "backlog_updates", []),
        "repo_fingerprint": getattr(record, "repo_fingerprint", {}),
        "verification": _safe(getattr(record, "verification", None)),
    }, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
