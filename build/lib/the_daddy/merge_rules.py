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
MAX_SAFE_FILES = 5
MAX_SAFE_PATCH_COUNT = 8
MAX_ARCHITECTURE_BRANCH_FILES = 5


class AutoMergeJudge:
    def __init__(self) -> None:
        pass

    def is_safe_file(self, path: str) -> bool:
        if any(part in path for part in RISKY_PATH_PARTS):
            return False
        return any(path.endswith(ext) for ext in SAFE_EXTENSIONS)

    def should_auto_merge(
        self,
        *,
        success: bool,
        policy_route: str,
        changed_files: Iterable[str],
        patch_count: int,
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        files = list(changed_files)

        if not success:
            reasons.append("Verification failed.")
        if policy_route != "safe":
            reasons.append(f"Policy route was {policy_route}, not safe.")
        if patch_count <= 0:
            reasons.append("No patches were applied.")
        if patch_count > MAX_SAFE_FILES:
            reasons.append(f"Patch count {patch_count} exceeds safe limit {MAX_SAFE_FILES}.")

        unsafe = [p for p in files if not self.is_safe_file(p)]
        if unsafe:
            reasons.append(f"Unsafe files touched: {', '.join(unsafe)}")

        return (len(reasons) == 0, reasons)
