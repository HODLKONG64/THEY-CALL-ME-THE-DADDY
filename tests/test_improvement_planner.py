from the_daddy.agents.improvement_planner import ImprovementPlanner
from the_daddy.models import ArchitectureReview, MemoryState, PatchAction, SelfEvolutionAction


def test_merge_review_into_backlog_adds_unique_items():
    planner = ImprovementPlanner()
    memory = MemoryState(backlog=["existing item"])
    review = ArchitectureReview(
        diagnosis="d",
        system_intent="i",
        recommendations=["existing item", "new recommendation"],
        backlog_items=["new backlog item"],
        self_evolution_actions=[],
        risk_level="low",
    )

    additions = planner.merge_review_into_backlog(memory, review)

    assert additions == ["new recommendation", "new backlog item"]
    assert memory.backlog == ["existing item", "new recommendation", "new backlog item"]


def test_plan_self_evolution_filters_to_safe_valid_actions():
    planner = ImprovementPlanner()
    review = ArchitectureReview(
        diagnosis="d",
        system_intent="i",
        self_evolution_actions=[
            SelfEvolutionAction(
                title="safe",
                description="desc",
                risk="safe",
                patches=[
                    PatchAction(
                        path="README.md",
                        operation="replace_file",
                        new_content="hello",
                        pattern=None,
                        replacement=None,
                        description="update",
                    )
                ],
            )
        ],
        risk_level="low",
    )

    planned = planner.plan_self_evolution(review, enabled=True, max_actions=3)

    assert planned.enabled is True
    assert len(planned.actions) == 1
    assert planned.actions[0].title == "safe"
    assert planned.reasons == []


def test_plan_self_evolution_normalizes_dict_actions_with_dict_patches():
    planner = ImprovementPlanner()
    review = ArchitectureReview(
        diagnosis="d",
        system_intent="i",
        self_evolution_actions=[],
        risk_level="low",
    )
    review.self_evolution_actions = [
        {
            "title": "Normalize payload",
            "description": "Accept dict-shaped safe action payloads.",
            "risk": "safe",
            "patches": [
                {
                    "path": "README.md",
                    "operation": "replace_file",
                    "new_content": "updated",
                    "pattern": None,
                    "replacement": None,
                    "description": "refresh docs",
                },
                {
                    "path": "",
                    "operation": "replace_file",
                    "new_content": "ignored",
                    "pattern": None,
                    "replacement": None,
                    "description": "invalid patch",
                },
            ],
        }
    ]

    planned = planner.plan_self_evolution(review, enabled=True, max_actions=3)

    assert planned.enabled is True
    assert len(planned.actions) == 1
    assert planned.actions[0].title == "Normalize payload"
    assert len(planned.actions[0].patches) == 1
    assert planned.actions[0].patches[0].path == "README.md"


def test_plan_self_evolution_returns_reason_when_disabled():
    planner = ImprovementPlanner()
    review = ArchitectureReview(
        diagnosis="d",
        system_intent="i",
        self_evolution_actions=[],
        risk_level="low",
    )

    planned = planner.plan_self_evolution(review, enabled=False, max_actions=3)

    assert planned.enabled is False
    assert planned.actions == []
    assert planned.reasons == ["Self-evolution disabled"]
