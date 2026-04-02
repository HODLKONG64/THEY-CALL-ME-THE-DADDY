from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .models import PatchAction


@dataclass
class PolicyResult:
    passed: bool
    route: str
    reasons: List[str]


SAFE_EXTENSIONS = {".py", ".md", ".yml", ".yaml", ".json", ".toml"}

# 🔒 HARD BLOCK — NEVER ALLOW THESE FILE NAMES
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
    "README_FIX.md",
    "THEY-CALL-ME-THE-DADDY",
}

# 🔒 HARD BLOCK — NEVER ALLOW THESE PATH SEGMENTS
BLOCKED_PATH_PARTS = {
    "build",
    "dist",
    "__pycache__",
    ".egg-info",
    "path",
}

# 🔒 DANGEROUS CODE PATTERNS
BLOCKED_KEYWORDS = {
    "rm -rf",
    "os.remove",
    "subprocess",
    "eval(",
    "exec(",
    "shutil.rmtree",
}

# 🔒 FORCE THESE FILES INTO PR FLOW ONLY
FORCE_BRANCH_PATHS = [
    ".github/workflows/",
    ".github/actions/",
]


def _is_workflow_file(path: str) -> bool:
    return any(path.startswith(p) for p in FORCE_BRANCH_PATHS)


def _is_blocked_path(path: str) -> list[str]:
    reasons = []

    parts = path.replace("\\", "/").split("/")

    if len(parts) == 1 and path in BLOCKED_ROOT_FILENAMES:
        reasons.append(f"Blocked root filename: {path}")

    for part in parts:
        if part in BLOCKED_PATH_PARTS:
            reasons.append(f"Blocked path segment: {part}")

    return reasons


def classify_patch_risk(patches: list[PatchAction]) -> PolicyResult:
    reasons: list[str] = []
    route = "safe"

    for patch in patches:
        path = patch.path.strip()

        # 🔒 PATH BLOCKING
        reasons.extend(_is_blocked_path(path))

        # 🔒 EXTENSION CHECK
        if not any(path.endswith(ext) for ext in SAFE_EXTENSIONS):
            reasons.append(f"Unsafe extension: {path}")

        # 🔒 CONTENT CHECK
        content = (patch.new_content or "") + (patch.pattern or "") + (patch.replacement or "")
        for bad in BLOCKED_KEYWORDS:
            if bad in content:
                reasons.append(f"Blocked keyword detected: {bad}")

        # 🔒 WORKFLOW FILES → FORCE PR
        if _is_workflow_file(path):
            route = "branch"

    if reasons:
        return PolicyResult(False, "reject", reasons)

    return PolicyResult(True, route, [])
