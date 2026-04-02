from types import SimpleNamespace

from the_daddy.agents.improvement_planner import ImprovementPlanner
from the_daddy.models import ArchitectureReview, MemoryState, SelfEvolutionAction


def test_merge_review_into_backlog_adds_new_items_once():
    planner = ImprovementPlanner()
    memory = MemoryState(backlog=["existing"])
    review = ArchitectureReview(
        diagnosis="diag",
        system_intent="intent",
        recommendations=["existing", "new recommendation"],
        backlog_items=["new backlog"],
    )

    additions = planner.merge_review_into_backlog(memory, review)

    assert additions == ["new recommendation", "new backlog"]
    assert memory.backlog == ["existing", "new recommendation", "new backlog"]


def test_plan_self_evolution_filters_safe_actions_and_caps_count():
    planner = ImprovementPlanner()
    review = ArchitectureReview(
        diagnosis="diag",
        system_intent="intent",
        self_evolution_actions=[
            SelfEvolutionAction(
                title="safe-1",
                description="desc",
                risk="safe",
                patches=[{"path": "README.md", "operation": "replace_file", "new_content": "x", "pattern": None, "replacement": None, "description": "desc"}],
            ),
            SelfEvolutionAction(
                title="branch",
                description="desc",
                risk="branch",
                patches=[{"path": "README.md", "operation": "replace_file", "new_content": "x", "pattern": None, "replacement": None, "description": "desc"}],
            ),
            SelfEvolutionAction(
                title="safe-2",
                description="desc",
                risk="safe",
                patches=[{"path": "ARCHITECTURE.md", "operation": "replace_file", "new_content": "x", "pattern": None, "replacement": None, "description": "desc"}],
            ),
        ],
    )

    planned = planner.plan_self_evolution(review, enabled=True, max_actions=1)

    assert planned.enabled is True
    assert len(planned.actions) == 1
    assert planned.actions[0].title == "safe-1"
    assert planned.reasons == ["Capped self-evolution actions from 2 to 1."]


def test_decide_mode_degrades_safely_for_partial_or_malformed_inputs():
    planner = ImprovementPlanner()

    memory_with_scalar_planned_work = SimpleNamespace(state=SimpleNamespace(planned_work="not-a-real-work-list"))
    review_with_none_fields = SimpleNamespace(architecture_plans=None, self_evolution_actions=None)
    assert planner.decide_mode(memory_with_scalar_planned_work, review_with_none_fields) == "build"

    memory_with_noniterable_planned_work = SimpleNamespace(state=SimpleNamespace(planned_work=object()))
    review_with_noniterable_fields = SimpleNamespace(architecture_plans=object(), self_evolution_actions=object())
    assert planner.decide_mode(memory_with_noniterable_planned_work, review_with_noniterable_fields) == "repair"

    memory_with_missing_state_fields = MemoryState()
    review_with_safe_action_placeholder = SimpleNamespace(
        architecture_plans=None,
        self_evolution_actions=[SimpleNamespace(risk="safe", patches=[])],
    )
    assert planner.decide_mode(memory_with_missing_state_fields, review_with_safe_action_placeholder) == "build"
