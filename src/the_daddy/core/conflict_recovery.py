from __future__ import annotations

from typing import Any


def summarize_conflict_state(
    *,
    pr_has_conflicts: bool,
    changed_files: list[str] | None = None,
    base_branch: str = "main",
) -> dict[str, Any]:
    files = [str(item).strip() for item in (changed_files or []) if str(item).strip()]
    return {
        "pr_has_conflicts": bool(pr_has_conflicts),
        "changed_files": files,
        "base_branch": base_branch or "main",
        "requires_recovery": bool(pr_has_conflicts),
    }


def build_conflict_recovery_plan(
    *,
    branch_name: str,
    changed_files: list[str] | None = None,
    base_branch: str = "main",
) -> dict[str, Any]:
    files = [str(item).strip() for item in (changed_files or []) if str(item).strip()]
    return {
        "branch_name": str(branch_name).strip(),
        "base_branch": str(base_branch).strip() or "main",
        "changed_files": files,
        "steps": [
            "fetch_latest_base",
            "rebase_or_recreate_branch",
            "reapply_bounded_patch",
            "rerun_verification",
            "push_recovery_branch",
            "open_replacement_pr",
        ],
    }


def summarize_conflict_recovery_result(
    *,
    attempted: bool,
    success: bool,
    branch_name: str,
    replacement_branch: str = "",
    notes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "attempted": bool(attempted),
        "success": bool(success),
        "branch_name": str(branch_name).strip(),
        "replacement_branch": str(replacement_branch).strip(),
        "notes": [str(item).strip() for item in (notes or []) if str(item).strip()],
    }
