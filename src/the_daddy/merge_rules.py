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
        if patch_count > MAX_SAFE_PATCH_COUNT:
            reasons.append(f"Patch count {patch_count} exceeds safe limit {MAX_SAFE_PATCH_COUNT}.")
        if len(files) > MAX_ARCHITECTURE_BRANCH_FILES:
            reasons.append(f"Changed file count {len(files)} exceeds safe limit {MAX_ARCHITECTURE_BRANCH_FILES}.")

        protected_touched = [p for p in files if p.strip().replace("\\", "/") in PROTECTED_CORE_FILES]
        if protected_touched:
            reasons.append(f"Protected core file modified: {', '.join(protected_touched)}")

        unsafe = [p for p in files if not self.is_safe_file(p)]
        if unsafe:
            reasons.append(f"Unsafe files touched: {', '.join(unsafe)}")

        return (len(reasons) == 0, reasons)


# daddy-review-guard
