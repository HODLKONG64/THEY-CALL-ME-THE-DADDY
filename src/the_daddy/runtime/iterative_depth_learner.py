from __future__ import annotations

from typing import Any


class IterativeDepthLearner:
    """
    Decision-only depth evaluator.

    It never creates or mutates patches.
    It only decides:
      - approve
      - reject
      - escalate_to_branch
    """

    def __init__(self, max_depth: int = 3) -> None:
        self.max_depth = max(1, min(int(max_depth), 5))

    def _depth_1_quick_safety(self, patches: list[dict[str, Any]]) -> dict[str, Any]:
        for patch in patches:
            path = str(patch.get("path", "")).strip()
            if not path or ".." in path:
                return {"ok": False, "reason": f"invalid_path:{path}"}
        return {"ok": True, "reason": "quick_safety_pass"}

    def _depth_2_repeat_scan(self, patches: list[dict[str, Any]], trace: list[dict[str, Any]]) -> dict[str, Any]:
        recent_failures = {
            str(event.get("path", "")).strip()
            for event in trace
            if isinstance(event, dict) and event.get("event") == "patch_apply_failed"
        }

        for patch in patches:
            path = str(patch.get("path", "")).strip()
            if path and path in recent_failures:
                return {"ok": False, "reason": f"recent_failure_repeat:{path}"}

        return {"ok": True, "reason": "repeat_scan_pass"}

    def _depth_3_stability_gate(
        self,
        *,
        patch_count: int,
        total_byte_delta: int,
        patches: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if patch_count > 5:
            return {"ok": False, "reason": "too_many_patches"}

        if total_byte_delta > 5000:
            return {"ok": False, "reason": "excessive_delta"}

        tiny_replace_files = 0
        for patch in patches:
            if patch.get("operation") == "replace_file":
                new_len = int(patch.get("new_content_length", 0) or 0)
                if 0 < new_len < 120:
                    tiny_replace_files += 1

        if tiny_replace_files >= 2:
            return {"ok": False, "reason": "too_many_tiny_replace_files"}

        return {"ok": True, "reason": "stability_pass"}

    def deepen(
        self,
        *,
        patches: list[dict[str, Any]],
        trace: list[dict[str, Any]],
        patch_count: int,
        total_byte_delta: int,
    ) -> dict[str, Any]:
        reasons: list[str] = []

        for depth in range(1, self.max_depth + 1):
            if depth == 1:
                result = self._depth_1_quick_safety(patches)
            elif depth == 2:
                result = self._depth_2_repeat_scan(patches, trace)
            else:
                result = self._depth_3_stability_gate(
                    patch_count=patch_count,
                    total_byte_delta=total_byte_delta,
                    patches=patches,
                )

            reasons.append(f"depth_{depth}:{result['reason']}")

            if not result["ok"]:
                return {
                    "decision": "reject",
                    "depth_reached": depth,
                    "reasons": reasons,
                }

        if patch_count >= 2 or total_byte_delta > 1500:
            return {
                "decision": "escalate_to_branch",
                "depth_reached": self.max_depth,
                "reasons": reasons,
            }

        return {
            "decision": "approve",
            "depth_reached": self.max_depth,
            "reasons": reasons,
        }
