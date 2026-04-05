from __future__ import annotations

from pathlib import Path
from typing import Any

def _coerce_run(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    if isinstance(item, dict):
        return dict(item)
    return {}

def recent_failed_runs(state: Any, limit: int = 3) -> list[dict[str, Any]]:
    runs = getattr(state, "runs", []) or []
    failed: list[dict[str, Any]] = []
    for item in reversed(runs):
        payload = _coerce_run(item)
        if not payload:
            continue
        if bool(payload.get("success", False)):
            continue
        failed.append(payload)
        if len(failed) >= max(1, int(limit)):
            break
    return failed

def summarize_failure_recovery_state(run_payload: dict[str, Any]) -> dict[str, Any]:
    rollback_manifest = run_payload.get("rollback_manifest", []) or []
    return {
        "run_id": str(run_payload.get("run_id", "")).strip(),
        "success": bool(run_payload.get("success", False)),
        "patch_count": int(run_payload.get("patch_count", 0) or 0),
        "rollback_count": len(rollback_manifest),
        "has_recovery_material": bool(rollback_manifest),
    }

def restore_from_rollback_manifest(
    repo_root: str | Path,
    rollback_manifest: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    root = Path(repo_root)
    manifest = rollback_manifest or []
    restored_paths: list[str] = []
    for item in manifest:
        path_text = str(item.get("path", "")).strip()
        old_content = item.get("old_content", "")
        if not path_text:
            continue
        target = root / path_text
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(old_content), encoding="utf-8")
        restored_paths.append(path_text)
    return {
        "restored_count": len(restored_paths),
        "restored_paths": restored_paths,
        "attempted": bool(manifest),
    }
