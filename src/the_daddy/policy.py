from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

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


def _normalize_masked_path(path: str) -> str:
    return path.replace("the_***", "the_daddy")


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


# Keywords that, when found inside a forbidden_repeat_patterns entry, indicate
# that README / doc-only / filler patches must be blocked at the policy layer.
_POLICY_README_FORBIDDEN_KEYWORDS: tuple[str, ...] = (
    "readme",
    "doc-only",
    "doc only",
    "helper-lane filler",
    "heartbeat",
    "filler",
)

# Sentinel value placed in target_files when the upgrade gate is bypassed.
# Enforcement must be skipped in this case.
_TARGET_FILES_BYPASS_SENTINEL = "gate_bypassed"


def _advice_readme_forbidden(upgrade_advice: dict[str, Any] | None) -> bool:
    """Return True if upgrade advice explicitly forbids README/doc-only/filler patches."""
    if not upgrade_advice:
        return False
    patterns = list(upgrade_advice.get("forbidden_repeat_patterns") or [])
    for pattern in patterns:
        pl = str(pattern).lower()
        if any(kw in pl for kw in _POLICY_README_FORBIDDEN_KEYWORDS):
            return True
    return False


def _advice_enforced_target_files(upgrade_advice: dict[str, Any] | None) -> set[str]:
    """Return the set of normalized target file paths that patches must be restricted to.

    Returns an empty set when:
    - upgrade_advice is None or missing target_files
    - target_files contains only the gate-bypass sentinel
    """
    if not upgrade_advice:
        return set()
    raw = list(upgrade_advice.get("target_files") or [])
    if not raw:
        return set()
    targets: set[str] = set()
    for item in raw:
        normalized = _normalize_masked_path(_normalize_path(str(item)))
        if normalized and normalized != _TARGET_FILES_BYPASS_SENTINEL:
            targets.add(normalized)
    # If all entries were the bypass sentinel, return empty (no enforcement).
    return targets


def classify_patch_risk(
    patches: list[PatchAction],
    upgrade_advice: dict[str, Any] | None = None,
) -> PolicyResult:
    reasons: list[str] = []
    route = "safe"

    readme_forbidden = _advice_readme_forbidden(upgrade_advice)
    enforced_targets = _advice_enforced_target_files(upgrade_advice)
    allowlisted_lower = {item.lower() for item in ALLOWLISTED_RUNTIME_HELPERS}

    for patch in patches:
        path = _normalize_masked_path(_normalize_path(patch.path))

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

        # --- OpenAI advice enforcement ---
        if readme_forbidden and path.lower() == "readme.md":
            reasons.append(
                f"OpenAI advice forbids README/doc patches: {path}"
            )

        if enforced_targets and path.lower() not in allowlisted_lower:
            if path not in enforced_targets and path.lower() not in {t.lower() for t in enforced_targets}:
                reasons.append(
                    f"OpenAI advice restricts patches to target_files; {path} is out of scope"
                )

    if reasons:
        return PolicyResult(False, "reject", reasons)

    return PolicyResult(True, route, [])
