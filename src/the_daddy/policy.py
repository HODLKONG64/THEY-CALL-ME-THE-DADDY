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
BLOCKED_KEYWORDS = {"rm -rf", "os.remove", "subprocess", "eval", "exec"}


def classify_patch_risk(patches: list[PatchAction]) -> PolicyResult:
    reasons = []

    for patch in patches:
        if not any(patch.path.endswith(ext) for ext in SAFE_EXTENSIONS):
            reasons.append(f"Unsafe extension: {patch.path}")

        content = (patch.new_content or "") + (patch.pattern or "") + (patch.replacement or "")
        for bad in BLOCKED_KEYWORDS:
            if bad in content:
                reasons.append(f"Blocked keyword detected: {bad}")

    if reasons:
        return PolicyResult(False, "reject", reasons)

    return PolicyResult(True, "safe", [])
