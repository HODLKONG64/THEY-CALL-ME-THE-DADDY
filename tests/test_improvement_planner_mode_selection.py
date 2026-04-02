from types import SimpleNamespace

from the_daddy.agents.improvement_planner import ImprovementPlanner
from the_daddy.models import FailurePattern, MemoryState


def _memory_with_failure_count(count: int) -> MemoryState:
    memory = MemoryState()
    memory.failure_patterns["test"] = FailurePattern(
        signature="test",
        failure_count=count,
        last_seen_output="",
        updated_at="2026-01-01T00:00:00Z",
    )
    return memory


def test_decide_mode_prefers_architecture_when_plans_exist_and_triggered():
    planner = ImprovementPlanner()
    memory = _memory_with_failure_count(3)
    review = SimpleNamespace(architecture_plans=[object()], self_evolution_actions=[])

    assert planner.decide_mode(memory, review) == "architecture"


def test_decide_mode_prefers_build_when_safe_review_actions_exist():
    planner = ImprovementPlanner()
    memory = MemoryState()
    review = SimpleNamespace(architecture_plans=[], self_evolution_actions=[object()])

    assert planner.decide_mode(memory, review) == "build"


def test_decide_mode_prefers_build_when_planned_work_exists():
    planner = ImprovementPlanner()
    memory = MemoryState(planned_work=[SimpleNamespace(state="proposed")])
    review = SimpleNamespace(architecture_plans=[], self_evolution_actions=[])

    assert planner.decide_mode(memory, review) == "build"


def test_decide_mode_falls_back_to_repair_when_review_fields_are_none():
    planner = ImprovementPlanner()
    memory = MemoryState()
    review = SimpleNamespace(architecture_plans=None, self_evolution_actions=None)

    assert planner.decide_mode(memory, review) == "repair"


def test_decide_mode_ignores_truthy_noniterable_placeholders_for_review_fields():
    planner = ImprovementPlanner()
    memory = MemoryState()

    class TruthyPlaceholder:
        def __bool__(self):
            return True

    review = SimpleNamespace(
        architecture_plans=TruthyPlaceholder(),
        self_evolution_actions=TruthyPlaceholder(),
    )

    mode = planner.decide_mode(memory, review)

    assert mode in {"build", "repair"}
