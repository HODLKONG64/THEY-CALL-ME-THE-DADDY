from types import SimpleNamespace

from the_daddy.agents.improvement_planner import ImprovementPlanner


class DummyFailurePattern:
    def __init__(self, failure_count: int = 0, updated_at: str = "") -> None:
        self.failure_count = failure_count
        self.updated_at = updated_at


def test_decide_mode_handles_missing_review_fields_and_falls_back_to_repair():
    planner = ImprovementPlanner()
    memory = SimpleNamespace(failure_patterns={}, planned_work=[])
    review = SimpleNamespace()

    assert planner.decide_mode(memory, review) == "repair"


def test_decide_mode_handles_none_iterables_and_uses_planned_work_build_fallback():
    planner = ImprovementPlanner()
    memory = SimpleNamespace(failure_patterns={}, planned_work=[SimpleNamespace(state="proposed")])
    review = SimpleNamespace(architecture_plans=None, self_evolution_actions=None)

    assert planner.decide_mode(memory, review) == "build"


def test_decide_mode_prefers_architecture_when_plans_exist_and_failure_threshold_is_met():
    planner = ImprovementPlanner()
    memory = SimpleNamespace(
        failure_patterns={"x": DummyFailurePattern(failure_count=3, updated_at="2026-04-02T00:00:00Z")},
        planned_work=[],
    )
    review = SimpleNamespace(architecture_plans=[SimpleNamespace()], self_evolution_actions=[])

    assert planner.decide_mode(memory, review) == "architecture"
