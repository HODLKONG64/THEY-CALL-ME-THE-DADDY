from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import PatchAction


@dataclass
class PatchScore:
    path: str
    score: float
    reasons: list[str]


@dataclass
class RankedPatchSet:
    total_score: float
    items: list[PatchScore]
    recommended_route: str
    reasons: list[str]


SAFE_FILE_BONUS = {
    ".py": 3.0,
    ".md": 1.0,
    ".json": 1.5,
    ".toml": 1.5,
    ".yml": 0.5,
    ".yaml": 0.5,
}

RISKY_PATH_PARTS = {
    ".github/workflows": -6.0,
    ".github/actions": -5.0,
    "build": -8.0,
    "dist": -8.0,
    "__pycache__": -10.0,
    ".egg-info": -10.0,
    "path": -10.0,
}

SUSPICIOUS_FILENAMES = {
    "bool": -20.0,
    "None": -20.0,
    "str": -20.0,
    "int": -20.0,
    "float": -20.0,
    "list": -20.0,
    "dict": -20.0,
    "tuple": -20.0,
    "set": -20.0,
    "README_FIX.md": -12.0,
    "THEY-CALL-ME-THE-DADDY": -20.0,
}

DANGEROUS_KEYWORDS = {
    "rm -rf": -25.0,
    "os.remove": -12.0,
    "subprocess": -8.0,
    "eval(": -15.0,
    "exec(": -15.0,
    "shutil.rmtree": -15.0,
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

ALLOWLISTED_RUNTIME_HELPERS = {
    "src/the_daddy/runtime/trace_summary.py",
    "src/the_daddy/runtime/reviewer_fallback.py",
    "src/the_daddy/runtime/architecture_probe.py",
}

LOW_VALUE_PATTERNS = [
    "trace",
    "logging",
    "observability",
]

DIVERSITY_TARGETS = [
    "engine",
    "memory",
    "planner",
    "merge",
    "policy",
    "diagnoser",
]


def _normalize_path(path: str) -> str:
    normalized = (path or "").strip().replace("\\", "/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _content_for_scoring(action: PatchAction) -> str:
    return (action.new_content or "") + (action.pattern or "") + (action.replacement or "")


def _value_score_bonus(path: str) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    normalized = _normalize_path(path)
    lowered = normalized.lower()

    if normalized in ALLOWLISTED_RUNTIME_HELPERS:
        score += 3.5
        reasons.append("allowlisted runtime helper bonus: +3.5")
        return score, reasons

    if any(pattern in lowered for pattern in LOW_VALUE_PATTERNS):
        score -= 2.5
        reasons.append("repeated low-value observability category: -2.5")

    if any(target in lowered for target in DIVERSITY_TARGETS):
        score += 3.0
        reasons.append("diversity target bonus: +3.0")

    return score, reasons


def score_patch(action: PatchAction) -> PatchScore:
    score = 0.0
    reasons: list[str] = []
    path = (action.path or "").strip()
    norm_path = _normalize_path(path)
    filename = norm_path.split("/")[-1] if norm_path else ""

    ext_bonus = 0.0
    for ext, bonus in SAFE_FILE_BONUS.items():
        if norm_path.endswith(ext):
            ext_bonus = bonus
            score += bonus
            reasons.append(f"safe extension bonus {ext}: +{bonus}")
            break

    if ext_bonus == 0.0:
        score -= 10.0
        reasons.append("unknown or unsafe extension: -10")

    for risky, penalty in RISKY_PATH_PARTS.items():
        if risky in norm_path:
            score += penalty
            reasons.append(f"risky path part {risky}: {penalty}")

    if filename in SUSPICIOUS_FILENAMES:
        penalty = SUSPICIOUS_FILENAMES[filename]
        score += penalty
        reasons.append(f"suspicious filename {filename}: {penalty}")

    if norm_path in PROTECTED_CORE_FILES:
        score -= 50.0
        reasons.append(f"protected core file {norm_path}: -50")

    value_bonus, value_reasons = _value_score_bonus(norm_path)
    score += value_bonus
    reasons.extend(value_reasons)

    content = _content_for_scoring(action)
    for keyword, penalty in DANGEROUS_KEYWORDS.items():
        if keyword in content:
            score += penalty
            reasons.append(f"dangerous keyword {keyword}: {penalty}")

    content_bytes = len(content.encode("utf-8", errors="ignore"))
    if content_bytes == 0:
        score -= 2.0
        reasons.append("empty patch content: -2")
    elif content_bytes < 100 and action.operation == "replace_file":
        if norm_path in ALLOWLISTED_RUNTIME_HELPERS:
            score += 0.5
            reasons.append("small allowlisted helper stub: +0.5")
        else:
            score -= 20.0
            reasons.append("tiny replace_file content (<100 bytes): -20")
    elif content_bytes < 4000:
        score += 1.5
        reasons.append("small bounded patch: +1.5")
    elif content_bytes < 20000:
        score += 0.5
        reasons.append("moderate patch size: +0.5")
    else:
        score -= 4.0
        reasons.append("large patch size: -4")

    if action.operation == "regex_replace":
        score += 0.5
        reasons.append("surgical regex patch: +0.5")

    if "test" in norm_path.lower():
        score += 1.0
        reasons.append("test-related file: +1")

    if norm_path.startswith("src/"):
        score += 1.0
        reasons.append("source file target: +1")

    return PatchScore(path=path, score=round(score, 2), reasons=reasons)


def rank_patch_set(actions: Iterable[PatchAction]) -> RankedPatchSet:
    items = [score_patch(action) for action in actions]
    total = round(sum(item.score for item in items), 2)

    reasons: list[str] = []
    recommended_route = "safe"

    if not items:
        return RankedPatchSet(
            total_score=0.0,
            items=[],
            recommended_route="safe",
            reasons=["no patches to score"],
        )

    min_item = min(item.score for item in items)
    protected_core_touched = any(_normalize_path(item.path) in PROTECTED_CORE_FILES for item in items)

    if protected_core_touched or min_item <= -15:
        recommended_route = "reject"
        reasons.append("at least one patch scored as clearly unsafe")
    elif any(".github/workflows/" in _normalize_path(item.path) or ".github/actions/" in _normalize_path(item.path) for item in items):
        recommended_route = "branch"
        reasons.append("workflow or action file present")
    elif total < 0:
        recommended_route = "recommend"
        reasons.append("patch set total score is negative")
    else:
        recommended_route = "safe"
        reasons.append("patch set is bounded and net positive")

    if len(items) > 8:
        if recommended_route == "safe":
            recommended_route = "recommend"
        reasons.append("too many patches in one set")

    return RankedPatchSet(
        total_score=total,
        items=items,
        recommended_route=recommended_route,
        reasons=reasons,
    )
