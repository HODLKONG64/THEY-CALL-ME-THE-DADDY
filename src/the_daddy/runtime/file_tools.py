from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Iterable, List

from ..models import FileSnapshot, PatchAction


IGNORE_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next"}


def truncate(text: str, limit: int = 50000) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n\n...[TRUNCATED]...\n\n" + text[-half:]


def is_safe_repo_path(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def should_ignore(path: Path) -> bool:
    return any(part in IGNORE_DIRS for part in path.parts)


def find_referenced_files(output: str, root: Path, allowed_exts: Iterable[str]) -> List[Path]:
    allowed = tuple(allowed_exts)
    found: set[Path] = set()
    patterns = [
        r'File "([^"]+)", line \d+',
        r"\(([^()]+\.(?:py|js|ts|tsx|jsx)):\d+:\d+\)",
        r"at ([^(]+?\.(?:js|ts|tsx|jsx)):\d+:\d+",
        r"([A-Za-z0-9_./\\-]+\.(?:py|js|ts|tsx|jsx|json|yml|yaml|toml|md))",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, output):
            candidate = Path(match.strip())
            if not candidate.is_absolute():
                candidate = root / candidate
            if candidate.exists() and candidate.is_file() and is_safe_repo_path(root, candidate):
                if not should_ignore(candidate) and candidate.suffix.lower() in allowed:
                    found.add(candidate)
    return sorted(found)


def gather_file_context(root: Path, paths: List[Path], max_files: int = 8, max_bytes: int = 120000) -> List[FileSnapshot]:
    snaps: List[FileSnapshot] = []
    for path in paths[:max_files]:
        content = path.read_text(encoding="utf-8", errors="ignore")
        if len(content.encode("utf-8")) > max_bytes:
            content = truncate(content, max_bytes // 2)
        snaps.append(FileSnapshot(path=str(path.relative_to(root)), content=content))
    return snaps


def unified_diff(old: str, new: str, path: str) -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    ))


def apply_patch_action(root: Path, change: PatchAction, allowed_exts: Iterable[str]) -> dict:
    target = (root / change.path).resolve()
    if not is_safe_repo_path(root, target):
        raise ValueError(f"Unsafe path: {change.path}")
    if target.suffix.lower() not in set(allowed_exts):
        raise ValueError(f"Extension not allowed: {change.path}")
    old = target.read_text(encoding="utf-8", errors="ignore") if target.exists() else ""
    if change.operation == "replace_file":
        if change.new_content is None:
            raise ValueError(f"Missing new_content for {change.path}")
        new = change.new_content
    elif change.operation == "regex_replace":
        if change.pattern is None or change.replacement is None:
            raise ValueError(f"Missing regex fields for {change.path}")
        new, count = re.subn(change.pattern, change.replacement, old, flags=re.MULTILINE | re.DOTALL)
        if count == 0:
            raise ValueError(f"Pattern not found in {change.path}")
    else:
        raise ValueError(f"Unsupported operation: {change.operation}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new, encoding="utf-8")
    return {
        "path": change.path,
        "description": change.description,
        "diff": unified_diff(old, new, change.path),
    }
