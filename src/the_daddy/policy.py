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

BLOCKED_KEYWORDS = {
    "rm -rf",
    "os.remove",
    "subprocess",
    "eval",
    "exec",
}


# 🔥 CRITICAL: files that MUST go through branch lane
FORCE_BRANCH_PATHS = [
    ".github/workflows/",
    ".github/actions/",
]


def _is_workflow_file(path: str) -> bool:
    return any(path.startswith(p) for p in FORCE_BRANCH_PATHS)


def classify_patch_risk(patches: list[PatchAction]) -> PolicyResult:
    reasons = []
    route = "safe"

    for patch in patches:
        path = patch.path

        # ❌ Extension safety
        if not any(path.endswith(ext) for ext in SAFE_EXTENSIONS):
            reasons.append(f"Unsafe extension: {path}")

        # ❌ Dangerous content
        content = (patch.new_content or "") + (patch.pattern or "") + (patch.replacement or "")
        for bad in BLOCKED_KEYWORDS:
            if bad in content:
                reasons.append(f"Blocked keyword detected: {bad}")

        # 🔥 CRITICAL FIX — workflow must go branch
        if _is_workflow_file(path):
            route = "branch"

    if reasons:
        return PolicyResult(False, "reject", reasons)

    return PolicyResult(True, route, [])