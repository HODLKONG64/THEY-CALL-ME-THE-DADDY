from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from .models import PatchAction


FORBIDDEN_SUBSTRINGS = [
    "rm -rf",
    "DROP TABLE",
    "subprocess.Popen(",
    "eval(",
    "exec(",
    "os.system(",
]


@dataclass
class PolicyResult:
    passed: bool
    route: str
    reasons: List[str]


def classify_patch_risk(changes: Iterable[PatchAction]) -> PolicyResult:
    changes = list(changes)
    reasons: List[str] = []
    route = "safe"

    if len(changes) > 8:
        reasons.append("Too many file changes in one plan.")
        route = "recommend"
    for change in changes:
        text = (change.new_content or "") + (change.replacement or "")
        if any(bad in text for bad in FORBIDDEN_SUBSTRINGS):
            reasons.append(f"Forbidden construct detected in {change.path}.")
            return PolicyResult(False, "reject", reasons)
        if change.path.startswith(".github/"):
            reasons.append("Workflow changes are medium/high risk.")
            route = "branch"
        if change.path.endswith((".env", ".pem", ".key")):
            reasons.append(f"Sensitive file target: {change.path}")
            return PolicyResult(False, "reject", reasons)
        if len(text.encode("utf-8")) > 200000:
            reasons.append(f"Patch too large for {change.path}.")
            route = "recommend"

    if not reasons and route == "safe":
        reasons.append("Patch set passed baseline policy.")
    return PolicyResult(True, route, reasons)
