# REPLACE FULL FILE

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable

from ..models import PatchAction


IGNORED_PARTS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "doctor_local"}

MAX_SHRINK_RATIO = 0.35  # NEW HARDEN RULE

PROTECTED_RUNTIME_FILES = {
    "src/the_daddy/runtime/trace_summary.py",  # NEW REGRESSION GUARD
}

PROTECTED_CORE_FILES = {
    "src/the_daddy/agents/reviewer.py",
    "src/the_daddy/engine.py",
    "src/the_daddy/models.py",
    "src/the_daddy/policy.py",
    "src/the_daddy/scoring.py",
    "src/the_daddy/merge_rules.py",
    "src/the_daddy/git_tools.py",
    "src/the_daddy/runtime/command_runner.py",
}


def _normalize_path(rel: str) -> str:
    return str(rel or "").strip().replace("\\", "/").replace("//", "/")


def _safe_target(root: Path, rel: str) -> Path:
    cleaned = _normalize_path(rel)
    if not cleaned:
        raise ValueError("Empty patch path")

    target = (root / cleaned).resolve()
    target.relative_to(root.resolve())
    return target


def _is_excessive_shrink(old_len: int, new_len: int) -> bool:
    if old_len == 0:
        return False
    shrink = (old_len - new_len) / old_len
    return shrink > MAX_SHRINK_RATIO


def apply_patch_action(root: Path, action: PatchAction, allow_extensions: Iterable[str]) -> dict:
    path = _normalize_path(action.path)
    target = _safe_target(root, path)

    if target.suffix not in set(allow_extensions):
        raise ValueError(f"Extension not allowed: {target.suffix}")

    old_content = target.read_text(encoding="utf-8", errors="ignore") if target.exists() else ""
    old_len = len(old_content.encode())

    if action.operation != "replace_file":
        raise ValueError("Only replace_file supported in hardened mode")

    new_content = action.new_content or ""
    new_len = len(new_content.encode())

    # 🚨 HARDEN RULE 1: MIN SIZE
    if new_len < 50:
        raise ValueError(f"Reject: new_content too small ({new_len})")

    # 🚨 HARDEN RULE 2: SHRINK PROTECTION
    if _is_excessive_shrink(old_len, new_len):
        raise ValueError(
            f"Reject: excessive shrink ({old_len} → {new_len})"
        )

    # 🚨 HARDEN RULE 3: REGRESSION GUARD
    if path in PROTECTED_RUNTIME_FILES and new_len < old_len:
        raise ValueError(
            f"Reject: regression risk on protected runtime file: {path}"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new_content, encoding="utf-8")

    return {
        "path": path,
        "bytes_before": old_len,
        "bytes_after": new_len,
    }
