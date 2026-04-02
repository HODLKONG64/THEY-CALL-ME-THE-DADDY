from types import SimpleNamespace

from the_daddy.agents.improvement_planner import ImprovementPlanner


class _FailurePattern:
    def __init__(self, failure_count, updated_at="2026-01-01T00:00:00+00:00"):
        self.failure_count = failure_count
        self.updated_at = updated_at


def _memory(*, planned_work=None, failure_patterns=None):
    return SimpleNamespace(
        planned_work=[] if planned_work is None else planned_work,
        failure_patterns={} if failure_patterns is None else failure_patterns,
    )


def _review(*, self_evolution_actions=None, architecture_plans=None):
    return SimpleNamespace(
        self_evolution_actions=[] if self_evolution_actions is None else self_evolution_actions,
        architecture_plans=[] if architecture_plans is None else architecture_plans,
    )


def test_decide_mode_prefers_architecture_when_plans_exist_and_failure_threshold_met():
    planner = ImprovementPlanner()
    memory = _memory(failure_patterns={"hotspot": _FailurePattern(3)})
    review = _review(architecture_plans=[{"title": "plan"}])

    assert planner.decide_mode(memory, review) == "architecture"


def test_decide_mode_prefers_build_when_safe_review_work_exists():
    planner = ImprovementPlanner()
    memory = _memory()
    review = _review(self_evolution_actions=[{"title": "safe action"}])

    assert planner.decide_mode(memory, review) == "build"


def test_decide_mode_prefers_build_when_planned_work_exists_without_review_actions():
    planner = ImprovementPlanner()
    memory = _memory(planned_work=[{"title": "queued"}])
    review = _review()

    assert planner.decide_mode(memory, review) == "build"


def test_decide_mode_falls_back_to_repair_when_review_fields_are_none():
    planner = ImprovementPlanner()
    memory = _memory()
    review = SimpleNamespace(self_evolution_actions=None, architecture_plans=None)

    assert planner.decide_mode(memory, review) == "repair"


def test_decide_mode_falls_back_to_repair_for_scalar_placeholder_review_fields():
    planner = ImprovementPlanner()
    memory = _memory()
    review = SimpleNamespace(self_evolution_actions=False, architecture_plans=0)

    assert planner.decide_mode(memory, review) == "repair"


def test_decide_mode_ignores_architecture_plan_when_failure_threshold_not_met():
    planner = ImprovementPlanner()
    memory = _memory(failure_patterns={"hotspot": _FailurePattern(2)})
    review = _review(architecture_plans=[{"title": "plan"}])

    assert planner.decide_mode(memory, review) == "repair"
