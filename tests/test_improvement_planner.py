from types import SimpleNamespace

from the_daddy.agents.improvement_planner import ImprovementPlanner


class FailurePattern:
    def __init__(self, failure_count: int, updated_at: str) -> None:
        self.failure_count = failure_count
        self.updated_at = updated_at


def test_decide_mode_prefers_architecture_when_triggered_and_plans_present():
    planner = ImprovementPlanner()
    state = SimpleNamespace(
        planned_work=[],
        failure_patterns={"hot": FailurePattern(3, "2026-01-01T00:00:00Z")},
    )
    review = SimpleNamespace(architecture_plans=[object()], self_evolution_actions=[])

    assert planner.decide_mode(state, review) == "architecture"


def test_decide_mode_falls_back_to_build_for_self_evolution_actions():
    planner = ImprovementPlanner()
    state = SimpleNamespace(planned_work=[], failure_patterns={})
    review = SimpleNamespace(architecture_plans=[], self_evolution_actions=[object()])

    assert planner.decide_mode(state, review) == "build"


def test_decide_mode_falls_back_to_build_for_planned_work_when_review_fields_missing():
    planner = ImprovementPlanner()
    state = SimpleNamespace(planned_work=[SimpleNamespace(state="proposed")], failure_patterns={})
    review = SimpleNamespace()

    assert planner.decide_mode(state, review) == "build"


def test_decide_mode_returns_repair_for_partial_non_iterable_inputs():
    planner = ImprovementPlanner()
    state = SimpleNamespace(planned_work=object(), failure_patterns={})
    review = SimpleNamespace(architecture_plans=object(), self_evolution_actions=object())

    assert planner.decide_mode(state, review) == "repair"


def test_decide_mode_handles_memory_wrapper_with_partial_state():
    planner = ImprovementPlanner()
    memory = SimpleNamespace(state=SimpleNamespace())
    review = SimpleNamespace()

    assert planner.decide_mode(memory, review) == "repair"
