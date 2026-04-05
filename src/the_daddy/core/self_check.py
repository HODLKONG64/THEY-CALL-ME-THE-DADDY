from __future__ import annotations

import json
from pathlib import Path
from typing import Any


RULES_PATH = Path("src/the_daddy/core/system_rules.json")


def load_rules() -> dict[str, Any]:
    if RULES_PATH.exists():
        return json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return {}


def summarize_self_check(
    *,
    pressure_score: int,
    runs_without_patches: int,
    success_rate: float,
    patch_count: int,
    had_build_actions: bool,
    had_self_evolution_actions: bool,
) -> dict[str, Any]:
    rules = load_rules()
    thresholds = rules.get("thresholds", {})

    force_pressure = int(thresholds.get("pressure_score_force_action", 6) or 6)
    no_patch_limit = int(thresholds.get("no_patch_streak_limit", 3) or 3)
    min_success = float(thresholds.get("success_rate_minimum", 0.7) or 0.7)

    empty_cycle = not had_build_actions and not had_self_evolution_actions
    pressured = pressure_score >= force_pressure or runs_without_patches >= no_patch_limit
    healthy_enough = success_rate >= min_success
    should_have_acted = pressured and healthy_enough

    violations: list[str] = []

    if rules.get("rules", {}).get("no_empty_cycles", False) and empty_cycle:
        violations.append("empty_cycle")

    if rules.get("rules", {}).get("require_patch_or_recovery", False):
        if should_have_acted and patch_count <= 0 and not had_build_actions and not had_self_evolution_actions:
            violations.append("required_patch_or_recovery_missing")

    if rules.get("rules", {}).get("force_patch_under_pressure", False):
        if pressured and patch_count <= 0 and not had_self_evolution_actions:
            violations.append("pressure_without_patch")

    score = 100
    score -= 25 * len(violations)
    if pressured and patch_count <= 0:
        score -= 10
    if success_rate < min_success:
        score -= 10
    score = max(0, score)

    return {
        "pressure_score": pressure_score,
        "runs_without_patches": runs_without_patches,
        "success_rate": success_rate,
        "patch_count": patch_count,
        "had_build_actions": had_build_actions,
        "had_self_evolution_actions": had_self_evolution_actions,
        "pressured": pressured,
        "healthy_enough": healthy_enough,
        "should_have_acted": should_have_acted,
        "violations": violations,
        "score": score,
        "passed": len(violations) == 0,
    }
