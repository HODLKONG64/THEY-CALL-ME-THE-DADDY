from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import Settings
from ..models import PatchAction


def _resolve_upgrade_path(path: str) -> str:
    if not isinstance(path, str):
        return path
    return path.replace("the_***", "the_daddy")


CLI_SOURCE = """from __future__ import annotations

import json
import sys

from .config import Settings
from .core.upgrade_gate import UpgradeGateError, validate_upgrade_gate_for_settings
from .engine import DaddyEngine


def get_settings() -> Settings:
    return Settings()


def _safe(value):
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def main() -> int:
    settings = get_settings()

    try:
        advice = validate_upgrade_gate_for_settings(settings)
    except UpgradeGateError as exc:
        print(f"Upgrade gate blocked execution: {exc}", file=sys.stderr)
        return 1

    if bool(advice.get("repair_mode", False)):
        print("Upgrade gate entered repair mode.", file=sys.stderr)

    engine = DaddyEngine(settings)
    record = engine.run()

    print(json.dumps({
        "run_id": getattr(record, "run_id", ""),
        "command": getattr(record, "command", ""),
        "selected_mode": getattr(record, "selected_mode", ""),
        "success": getattr(record, "success", False),
        "summary": getattr(record, "summary", ""),
        "patch_count": len(getattr(record, "patches_applied", []) or []),
        "patches_applied": getattr(record, "patches_applied", []),
        "rollback_manifest": getattr(record, "rollback_manifest", []),
        "trace": getattr(record, "trace", []),
        "backlog_updates": getattr(record, "backlog_updates", []),
        "repo_fingerprint": getattr(record, "repo_fingerprint", {}),
        "verification": _safe(getattr(record, "verification", None)),
    }, indent=2))

    return 0 if getattr(record, "success", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
"""


class DoctorExecutor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _normalize_path(self, value: str) -> str:
        return str(value or "").replace("\\", "/").strip().lower()

    def plan_patches(
        self,
        *,
        repo_root: Path,
        advice: dict[str, Any],
        trace_tail: list[dict[str, Any]] | None = None,
        file_snapshots: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        target_files = []
        for item in list(advice.get("target_files", []) or []):
            if not str(item).strip():
                continue
            target_files.append(_resolve_upgrade_path(self._normalize_path(str(item))))

        changes: list[PatchAction] = []

        if "src/the_daddy/cli.py" in target_files:
            changes.append(
                PatchAction(
                    path="src/the_daddy/cli.py",
                    operation="replace_file",
                    new_content=CLI_SOURCE,
                    description="Replace CLI with strict runtime upgrade-gate enforcement that reuses core validation.",
                )
            )

        diagnosis = (
            "Doctor executor performed a local bounded takeover using the already-approved "
            "OpenAI repair scope, without making another OpenAI request."
        )
        root_cause = (
            "The prior stuck path came from relying on an OpenAI-backed diagnoser during takeover. "
            "Local doctor execution avoids repeated remote escalation and applies the bounded runtime fix directly."
        )

        return {
            "diagnosis": diagnosis,
            "root_cause": root_cause,
            "changes": changes,
            "trace_tail": trace_tail or [],
            "file_snapshot_count": len(file_snapshots or []),
        }
