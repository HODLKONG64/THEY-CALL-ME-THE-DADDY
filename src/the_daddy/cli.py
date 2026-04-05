from __future__ import annotations

import json
import os
import sys

from .config import Settings
from .engine import DaddyEngine


def get_settings() -> Settings:
    return Settings()


def _is_repair_mode() -> bool:
    path = os.environ.get("DADDY_UPGRADE_ADVICE_PATH")
    if not path or not os.path.exists(path):
        return False
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return not data.get("allow_proceed", False)
    except Exception:
        return False


def main() -> int:
    settings = get_settings()
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
        "verification": getattr(record, "verification", None),
    }, indent=2))

    # HARD STOP only if NOT in repair mode
    if not _is_repair_mode():
        if not getattr(engine, "upgrade_advice", None):
            print("Upgrade gate missing approved advice.", file=sys.stderr)
            return 1
        if not engine.upgrade_advice.get("allow_proceed", False):
            print("Upgrade not approved.", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
