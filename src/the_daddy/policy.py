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

BLOCKED_PATH_PARTS = {
    "build",
    "dist",
    "__pycache__",
    ".egg-info",
    "path",
}

BLOCKED_KEYWORDS = {
    "rm -rf",
    "os.remove",
    "subprocess",
    "eval(",
    "exec(",
    "shutil.rmtree",
}

FORCE_BRANCH_PATHS = [
    ".github/workflows/",
    ".github/actions/",
]

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

REPAIR_GATE_TARGET_FILES = {
    "src/the_daddy/engine.py",
    "src/the_daddy/core/upgrade_gate.py",
    "src/the_daddy/core/require_upgrade_advice.py",
    "src/the_daddy/cli.py",
}

BANNED_SELF_EVOLUTION_PATHS = {
    "src/the_daddy/runtime/command_runner.py",
}

ALLOWLISTED_RUNTIME_HELPERS = {
    "src/the_daddy/runtime/trace_summary.py",
    "src/the_daddy/runtime/reviewer_fallback.py",
    "src/the_daddy/runtime/architecture_probe.py",
    "src/the_daddy/runtime/error_digest.py",
    "src/the_daddy/runtime/run_health.py",
}


def _normalize_path(path: str) -> str:
    normalized = (path or "").strip().replace("\\", "/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _is_workflow_file(path: str) -> bool:
    normalized = _normalize_path(path)
    return any(normalized.startswith(prefix) for prefix in FORCE_BRANCH_PATHS)


def _is_blocked_path(path: str) -> list[str]:
    reasons: list[str] = []
    normalized = _normalize_path(path)
    parts = normalized.split("/")

    if len(parts) == 1 and normalized in BLOCKED_ROOT_FILENAMES:
        reasons.append(f"Blocked root filename: {normalized}")

    for part in parts:
        if part in BLOCKED_PATH_PARTS:
            reasons.append(f"Blocked path segment: {part}")

    return reasons


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


def classify_patch_risk(patches: list[PatchAction]) -> PolicyResult:
    reasons: list[str] = []
    route = "safe"

    for patch in patches:
        path = _normalize_path(patch.path)

        if not path:
            reasons.append("Empty patch path")
            continue

        reasons.extend(_is_blocked_path(path))

        if not any(path.endswith(ext) for ext in SAFE_EXTENSIONS):
            reasons.append(f"Unsafe extension: {path}")

        if path in PROTECTED_CORE_FILES and path not in REPAIR_GATE_TARGET_FILES:
            reasons.append(f"Protected core file cannot be auto-patched: {path}")

        if path in BANNED_SELF_EVOLUTION_PATHS:
            reasons.append(f"Banned self-evolution path: {path}")

        content = (patch.new_content or "") + (patch.pattern or "") + (patch.replacement or "")
        for bad in BLOCKED_KEYWORDS:
            if bad in content:
                reasons.append(f"Blocked keyword detected: {bad}")

        if _is_workflow_file(path):
            route = "branch"

        if _looks_like_hallucinated_path(path):
            reasons.append(f"Blocked hallucinated or near-miss path: {path}")

    if reasons:
        return PolicyResult(False, "reject", reasons)

    return PolicyResult(True, route, [])
