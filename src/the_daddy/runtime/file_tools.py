from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Iterable

from ..models import PatchAction


IGNORED_PARTS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "doctor_local"}

BLOCKED_ROOT_FILENAMES = {
    "bool",
    "None",
    "str",
    "int",
    "float",
    "list",
    "dict",
    "tuple",
    "set",
    "path",
    "Path",
    "THEY-CALL-ME-THE-DADDY",
    "README_FIX.md",
}

BLOCKED_PATH_PARTS = {
    "build",
    "dist",
    "__pycache__",
    ".egg-info",
    "path",
}

MAX_SHRINK_RATIO = 0.35
MIN_NEW_FILE_BYTES = 50

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

PROTECTED_RUNTIME_FILES = {
    "src/the_daddy/runtime/trace_summary.py",
}

SAFE_NEW_FILE_ALLOWLIST = {
    "src/the_daddy/runtime/trace_summary.py",
    "src/the_daddy/runtime/reviewer_fallback.py",
    "src/the_daddy/runtime/architecture_probe.py",
    "src/the_daddy/runtime/error_digest.py",
    "src/the_daddy/runtime/run_health.py",
}


def _normalize_path(rel: str) -> str:
    cleaned = str(rel or "").strip().replace("\\", "/")
    while "//" in cleaned:
        cleaned = cleaned.replace("//", "/")
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned




def _is_test_context() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ

def _looks_like_hallucinated_path(path: str) -> bool:
    normalized = _normalize_path(path)

    if normalized == "src/the_daddy/reviewer.py":
        return True

    if normalized in PROTECTED_CORE_FILES:
        return False

    if normalized.startswith("src/the_daddy/runtime/"):
        return False

    if normalized.startswith("src/the_daddy/"):
        remainder = normalized[len("src/the_daddy/"):]
        if "/" not in remainder:
            return True

    return False


def _safe_target(root: Path, rel: str) -> Path:
    cleaned = _normalize_path(rel)

    if not cleaned:
        raise ValueError("Empty patch path")

    # Keep production patching locked to src/the_daddy, but allow isolated unit tests
    # to exercise file operations against temporary files.
    if not cleaned.startswith("src/the_daddy/"):
        if not _is_test_context():
            raise ValueError(f"Blocked patch outside allowed scope: {cleaned}")

    if cleaned in {".", "./", "/"}:
        raise ValueError(f"Invalid patch path: {rel}")

    if cleaned.endswith("/"):
        raise ValueError(f"Patch path points to a directory, not a file: {rel}")

    if _looks_like_hallucinated_path(cleaned):
        raise ValueError(f"Blocked hallucinated or unapproved patch path: {cleaned}")

    target = (root / cleaned).resolve()
    root_resolved = root.resolve()

    target.relative_to(root_resolved)

    if target.parent == root_resolved and target.name in BLOCKED_ROOT_FILENAMES:
        raise ValueError(f"Blocked suspicious root filename: {target.name}")

    relative_parts = target.relative_to(root_resolved).parts
    if any(part in BLOCKED_PATH_PARTS for part in relative_parts):
        raise ValueError(f"Blocked artifact path: {cleaned}")

    return target


def _is_excessive_shrink(old_len: int, new_len: int) -> bool:
    if old_len <= 0:
        return False
    shrink = (old_len - new_len) / old_len
    return shrink > MAX_SHRINK_RATIO


def find_referenced_files(output: str, root: Path, allow_extensions: Iterable[str]) -> list[Path]:
    found: list[Path] = []
    exts = tuple(allow_extensions)

    normalized_exts = [ext.lstrip(".") for ext in exts if isinstance(ext, str) and ext.strip()]
    if not normalized_exts:
        return found

    ext_pattern = "|".join(re.escape(ext) for ext in normalized_exts)
    pattern = rf"([A-Za-z0-9_./\\-]+\.(?:{ext_pattern}))"

    for match in re.findall(pattern, output):
        try:
            p = _safe_target(root, match)
        except Exception:
            continue

        if (
            p.exists()
            and p.is_file()
            and p.suffix in exts
            and not any(part in IGNORED_PARTS for part in p.parts)
        ):
            if p not in found:
                found.append(p)

    return found[:8]


def gather_file_context(root: Path, files: list[Path], max_files: int = 8, max_bytes: int = 120000):
    contexts = []
    for p in files[:max_files]:
        text = p.read_text(encoding="utf-8", errors="ignore")

        contexts.append(
            type(
                "FileContext",
                (),
                {
                    "path": str(p.relative_to(root)),
                    "content": text[:max_bytes],
                    "model_dump": lambda self, mode="json": {
                        "path": self.path,
                        "content": self.content,
                    },
                },
            )()
        )

    return contexts


def apply_patch_action(root: Path, action: PatchAction, allow_extensions: Iterable[str]) -> dict:
    norm_path = _normalize_path(action.path)
    target = _safe_target(root, norm_path)

    if target.suffix not in set(allow_extensions):
        raise ValueError(f"Extension not allowed: {target.suffix}")

    target_exists = target.exists()

    if action.operation == "replace_file":
        if action.new_content is None:
            raise ValueError("replace_file missing new_content")

        if norm_path in PROTECTED_CORE_FILES:
            raise ValueError(f"Reject: protected core file cannot be modified by auto-patch: {norm_path}")

        if not target_exists and norm_path not in SAFE_NEW_FILE_ALLOWLIST:
            raise ValueError(f"Reject: new file creation not allowed outside safe allowlist: {norm_path}")

        target.parent.mkdir(parents=True, exist_ok=True)

        old_content = target.read_text(encoding="utf-8", errors="ignore") if target_exists else ""
        old_hash = hashlib.sha256(old_content.encode("utf-8", errors="ignore")).hexdigest()

        new_content = action.new_content
        new_len = len(new_content)
        old_len = len(old_content)

        if not target_exists and new_len < MIN_NEW_FILE_BYTES:
            raise ValueError(
                f"Reject: new_content too small ({new_len} bytes) for new file {norm_path}"
            )

        if _is_excessive_shrink(old_len, new_len):
            raise ValueError(
                f"Reject: excessive shrink detected for {norm_path} "
                f"(old={old_len} bytes, new={new_len} bytes, ratio={new_len / old_len:.2f})"
            )

        if norm_path in PROTECTED_RUNTIME_FILES and old_len > 0 and new_len < old_len:
            raise ValueError(
                f"Reject: regression risk on protected runtime file: {norm_path}"
            )

    else:
        if action.pattern is None or action.replacement is None:
            raise ValueError("regex_replace missing pattern/replacement")

        if not target_exists:
            raise ValueError(f"Reject: regex_replace target does not exist: {norm_path}")

        old_content = target.read_text(encoding="utf-8", errors="ignore")
        old_hash = hashlib.sha256(old_content.encode("utf-8", errors="ignore")).hexdigest()

        new_content, count = re.subn(
            action.pattern,
            action.replacement,
            old_content,
            flags=re.MULTILINE | re.DOTALL,
        )

        if count == 0:
            raise ValueError(f"Pattern not found in {norm_path}")

    target.write_text(new_content, encoding="utf-8")

    new_hash = hashlib.sha256(new_content.encode("utf-8", errors="ignore")).hexdigest()

    return {
        "path": norm_path,
        "description": action.description,
        "old_hash": old_hash,
        "new_hash": new_hash,
        "bytes_before": len(old_content.encode("utf-8")),
        "bytes_after": len(new_content.encode("utf-8")),
        "rollback": {
            "path": norm_path,
            "old_content": old_content if len(old_content.encode("utf-8")) <= 50000 else None,
            "old_hash": old_hash,
        },
    }