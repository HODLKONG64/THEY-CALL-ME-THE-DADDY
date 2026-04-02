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


def _content_for_scoring(action: PatchAction) -> str:
    return (action.new_content or "") + (action.pattern or "") + (action.replacement or "")


def score_patch(action: PatchAction) -> PatchScore:
    score = 0.0
    reasons: list[str] = []
    path = action.path.strip()
    filename = path.replace("\\", "/").split("/")[-1]

    ext_bonus = 0.0
    for ext, bonus in SAFE_FILE_BONUS.items():
        if path.endswith(ext):
            ext_bonus = bonus
            score += bonus
            reasons.append(f"safe extension bonus {ext}: +{bonus}")
            break

    if ext_bonus == 0.0:
        score -= 10.0
        reasons.append("unknown or unsafe extension: -10")

    for risky, penalty in RISKY_PATH_PARTS.items():
        if risky in path.replace("\\", "/"):
            score += penalty
            reasons.append(f"risky path part {risky}: {penalty}")

    if filename in SUSPICIOUS_FILENAMES:
        penalty = SUSPICIOUS_FILENAMES[filename]
        score += penalty
        reasons.append(f"suspicious filename {filename}: {penalty}")

    content = _content_for_scoring(action)
    for keyword, penalty in DANGEROUS_KEYWORDS.items():
        if keyword in content:
            score += penalty
            reasons.append(f"dangerous keyword {keyword}: {penalty}")

    content_bytes = len(content.encode("utf-8", errors="ignore"))
    if content_bytes == 0:
        score -= 2.0
        reasons.append("empty patch content: -2")
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

    if "test" in path.lower():
        score += 1.0
        reasons.append("test-related file: +1")

    if path.startswith("src/"):
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

    if min_item <= -10:
        recommended_route = "reject"
        reasons.append("at least one patch scored as clearly unsafe")
    elif any(".github/workflows/" in item.path or ".github/actions/" in item.path for item in items):
        recommended_route = "branch"
        reasons.append("workflow or action file present")
    elif total < 0:
        recommended_route = "recommend"
        reasons.append("patch set total score is negative")
    else:
        recommended_route = "safe"
        reasons.append("patch set is bounded and net positive")

    if len(items) > 8:
        recommended_route = "recommend" if recommended_route == "safe" else recommended_route
        reasons.append("too many patches in one set")

    return RankedPatchSet(
        total_score=total,
        items=items,
        recommended_route=recommended_route,
        reasons=reasons,
    )
