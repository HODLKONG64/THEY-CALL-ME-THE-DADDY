from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable

from ..models import PatchAction


IGNORED_PARTS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "doctor_local"}


def _safe_target(root: Path, rel: str) -> Path:
    target = (root / rel).resolve()
    target.relative_to(root.resolve())
    return target


def find_referenced_files(output: str, root: Path, allow_extensions: Iterable[str]) -> list[Path]:
    found: list[Path] = []
    exts = tuple(allow_extensions)
    for match in re.findall(r"([A-Za-z0-9_./\\-]+\.(?:py|md|yml|yaml|json|txt))", output):
        p = (root / match).resolve()
        try:
            p.relative_to(root.resolve())
        except Exception:
            continue
        if p.exists() and p.is_file() and p.suffix in exts and not any(part in IGNORED_PARTS for part in p.parts):
            if p not in found:
                found.append(p)
    return found[:8]


def gather_file_context(root: Path, files: list[Path], max_files: int = 8, max_bytes: int = 120000):
    contexts = []
    for p in files[:max_files]:
        text = p.read_text(encoding="utf-8", errors="ignore")
        contexts.append(type("FileContext", (), {"path": str(p.relative_to(root)), "content": text[:max_bytes], "model_dump": lambda self, mode="json": {"path": self.path, "content": self.content}})())
    return contexts


def apply_patch_action(root: Path, action: PatchAction, allow_extensions: Iterable[str]) -> dict:
    target = _safe_target(root, action.path)
    if target.suffix not in set(allow_extensions):
        raise ValueError(f"Extension not allowed: {target.suffix}")
    target.parent.mkdir(parents=True, exist_ok=True)
    old_content = target.read_text(encoding="utf-8", errors="ignore") if target.exists() else ""
    old_hash = hashlib.sha256(old_content.encode("utf-8", errors="ignore")).hexdigest()

    if action.operation == "replace_file":
        if action.new_content is None:
            raise ValueError("replace_file missing new_content")
        new_content = action.new_content
    else:
        if action.pattern is None or action.replacement is None:
            raise ValueError("regex_replace missing pattern/replacement")
        new_content, count = re.subn(action.pattern, action.replacement, old_content, flags=re.MULTILINE | re.DOTALL)
        if count == 0:
            raise ValueError(f"Pattern not found in {action.path}")

    target.write_text(new_content, encoding="utf-8")
    new_hash = hashlib.sha256(new_content.encode("utf-8", errors="ignore")).hexdigest()
    return {
        "path": action.path,
        "description": action.description,
        "old_hash": old_hash,
        "new_hash": new_hash,
        "bytes_before": len(old_content.encode("utf-8")),
        "bytes_after": len(new_content.encode("utf-8")),
        "rollback": {
            "path": action.path,
            "old_content": old_content if len(old_content.encode("utf-8")) <= 50000 else None,
            "old_hash": old_hash,
        },
    }
