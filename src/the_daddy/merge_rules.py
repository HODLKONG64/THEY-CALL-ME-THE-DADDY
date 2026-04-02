# REPLACE FULL FILE

from typing import Iterable

MAX_AUTO_MERGE_BYTE_DELTA = 1200
MAX_SAFE_PATCH_COUNT = 5

LOW_VALUE_KEYWORDS = ["logging", "trace", "observability"]


class AutoMergeJudge:
    def is_safe_file(self, path: str) -> bool:
        return path.endswith((".py", ".md", ".json", ".yml", ".toml"))

    def _is_low_value_loop(self, files: list[str]) -> bool:
        return all(any(k in f for k in LOW_VALUE_KEYWORDS) for f in files)

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

        reasons = []
        files = list(changed_files)

        if not success:
            reasons.append("tests failed")

        if policy_route != "safe":
            reasons.append("not safe route")

        if patch_count > MAX_SAFE_PATCH_COUNT:
            reasons.append("too many patches")

        if total_byte_delta > MAX_AUTO_MERGE_BYTE_DELTA:
            reasons.append("diff too large")

        if review_risk != "low":
            reasons.append("risk not low")

        # 🧠 LEVEL UP: detect boring loops
        if self._is_low_value_loop(files):
            reasons.append("low-value repeated patch type")

        return (len(reasons) == 0, reasons)
