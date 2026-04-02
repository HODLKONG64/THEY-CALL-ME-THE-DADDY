from __future__ import annotations

from typing import Iterable


SAFE_EXTENSIONS = {".py", ".md", ".yml", ".yaml", ".json", ".toml"}
RISKY_PATH_PARTS = {
    ".github/workflows",
    "secrets",
    ".env",
    "node_modules",
    "dist",
    "build",
}
MAX_SAFE_PATCH_COUNT = 8
MAX_ARCHITECTURE_BRANCH_FILES = 5
MAX_AUTO_MERGE_BYTE_DELTA = 1200

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


class AutoMergeJudge:
    def __init__(self) -> None:
        pass

    def is_safe_file(self, path: str) -> bool:
        if any(part in path for part in RISKY_PATH_PARTS):
            return False
        return any(path.endswith(ext) for ext in SAFE_EXTENSIONS)

    def _is_low_value_loop(self, files: list[str]) -> bool:
        lowered = [p.lower() for p in files]
        return bool(lowered) and all(any(k in p for k in ("logging", "trace", "observability")) for p in lowered)

    def should_auto_merge(
        self,
        *,
        success: bool,
        policy_route: str,
        changed_files: Iterable[str],
        patch_count: int,
        total_byte_delta: int,
        review_risk: str,
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        files = list(changed_files)

        if not success:
            reasons.append("Verification failed.")
        if policy_route != "safe":
            reasons.append(f"Policy route was {policy_route}, not safe.")
        if patch_count <= 0:
            reasons.append("No patches were applied.")
        if patch_count > MAX_SAFE_PATCH_COUNT:
            reasons.append(f"Patch count {patch_count} exceeds safe limit {MAX_SAFE_PATCH_COUNT}.")
        if len(files) > MAX_ARCHITECTURE_BRANCH_FILES:
            reasons.append(f"Changed file count {len(files)} exceeds safe limit {MAX_ARCHITECTURE_BRANCH_FILES}.")
        if (review_risk or "").lower() != "low":
            reasons.append(f"Review risk was {review_risk}, not low.")
        if total_byte_delta > MAX_AUTO_MERGE_BYTE_DELTA:
            reasons.append(
                f"Patch byte delta {total_byte_delta} exceeds auto-merge threshold {MAX_AUTO_MERGE_BYTE_DELTA}."
            )

        protected_touched = [p for p in files if p.strip().replace("\\", "/") in PROTECTED_CORE_FILES]
        if protected_touched:
            reasons.append(f"Protected core file modified: {', '.join(protected_touched)}")

        unsafe = [p for p in files if not self.is_safe_file(p)]
        if unsafe:
            reasons.append(f"Unsafe files touched: {', '.join(unsafe)}")

        if self._is_low_value_loop(files):
            reasons.append("Low-value repeated patch category.")

        return (len(reasons) == 0, reasons)
