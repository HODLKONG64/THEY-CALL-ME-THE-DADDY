from __future__ import annotations

from typing import Any, Dict, List


class IterativeDepthLearner:
    """
    Decision-only depth evaluator.

    It NEVER creates or mutates patches.
    It only decides:
      - approve
      - reject
      - escalate_to_branch

    based on progressively deeper analysis.
    """

    def __init__(self, max_depth: int = 3) -> None:
        self.max_depth = max(1, min(max_depth, 5))  # hard cap safety

    def _depth_1_quick_safety(self, patches: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Fast sanity check.
        """
        for p in patches:
            path = str(p.get("path", ""))
            if not path or ".." in path:
                return {"ok": False, "reason": f"invalid_path:{path}"}

        return {"ok": True, "reason": "quick_safety_pass"}

    def _depth_2_impact_scan(
        self,
        patches: List[Dict[str, Any]],
        trace: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Look for known failure patterns + risky behavior.
        """
        recent_failures = {
            str(e.get("path", ""))
            for e in trace
            if e.get("event") == "patch_apply_failed"
        }

        for p in patches:
            if p.get("path") in recent_failures:
                return {
                    "ok": False,
                    "reason": f"recent_failure_repeat:{p.get('path')}",
                }

        return {"ok": True, "reason": "impact_scan_pass"}

    def _depth_3_stability_check(
        self,
        patch_count: int,
        total_byte_delta: int,
    ) -> Dict[str, Any]:
        """
        Enforce bounded change discipline.
        """
        if patch_count > 5:
            return {"ok": False, "reason": "too_many_patches"}

        if total_byte_delta > 5000:
            return {"ok": False, "reason": "excessive_delta"}

        return {"ok": True, "reason": "stability_pass"}

    def deepen(
        self,
        patches: List[Dict[str, Any]],
        trace: List[Dict[str, Any]],
        patch_count: int,
        total_byte_delta: int,
    ) -> Dict[str, Any]:
        """
        Main entry.

        Returns:
        {
            "decision": "approve" | "reject" | "escalate_to_branch",
            "depth_reached": int,
            "reasons": [str]
        }
        """

        reasons: List[str] = []

        for depth in range(1, self.max_depth + 1):
            if depth == 1:
                result = self._depth_1_quick_safety(patches)

            elif depth == 2:
                result = self._depth_2_impact_scan(patches, trace)

            elif depth >= 3:
                result = self._depth_3_stability_check(
                    patch_count,
                    total_byte_delta,
                )

            else:
                result = {"ok": True, "reason": "noop"}

            reasons.append(f"depth_{depth}:{result['reason']}")

            if not result["ok"]:
                return {
                    "decision": "reject",
                    "depth_reached": depth,
                    "reasons": reasons,
                }

        # escalation logic (clean but non-trivial change)
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
