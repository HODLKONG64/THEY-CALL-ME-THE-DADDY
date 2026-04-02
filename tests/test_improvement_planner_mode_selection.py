from types import SimpleNamespace

from the_daddy.agents.improvement_planner import ImprovementPlanner


class DummyMemory:
    def __init__(self, planned_work=None, failure_patterns=None):
        self.planned_work = [] if planned_work is None else planned_work
        self.failure_patterns = {} if failure_patterns is None else failure_patterns


def test_decide_mode_prefers_repair_when_review_fields_are_missing_lists():
    planner = ImprovementPlanner()
    memory = DummyMemory(planned_work=[])
    review = SimpleNamespace(architecture_plans=[], self_evolution_actions=[])

    assert planner.decide_mode(memory, review) == "repair"


def test_decide_mode_uses_build_when_safe_review_actions_exist_even_if_memory_is_minimal():
    planner = ImprovementPlanner()
    memory = DummyMemory()
    review = SimpleNamespace(
        architecture_plans=[],
        self_evolution_actions=[SimpleNamespace(risk="safe", patches=[object()])],
    )

    assert planner.decide_mode(memory, review) == "build"


def test_decide_mode_uses_build_when_memory_has_planned_work_and_review_is_empty():
    planner = ImprovementPlanner()
    memory = DummyMemory(planned_work=[SimpleNamespace(state="proposed")])
    review = SimpleNamespace(architecture_plans=[], self_evolution_actions=[])

    assert planner.decide_mode(memory, review) == "build"


def test_decide_mode_handles_wrapped_memory_state_shape():
    planner = ImprovementPlanner()
    state = DummyMemory(planned_work=[SimpleNamespace(state="active")])
    wrapped_memory = SimpleNamespace(state=state)
    review = SimpleNamespace(architecture_plans=[], self_evolution_actions=[])

    assert planner.decide_mode(wrapped_memory, review) == "build"
