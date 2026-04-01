from the_daddy.agents.improvement_planner import ImprovementPlanner
from the_daddy.models import ArchitectureReview, PatchAction, MemoryState


def test_merge_review_into_backlog_adds_recommendations_and_backlog_items():
    planner = ImprovementPlanner()
    memory = MemoryState()
    review = ArchitectureReview(
        diagnosis="ok",
        system_intent="self evolving",
        recommendations=["add drift detector"],
        backlog_items=["track applied improvements"],
        self_evolution_actions=[],
        execution_notes=[],
        risk_level="low",
    )

    added = planner.merge_review_into_backlog(memory, review)

    assert "add drift detector" in added
    assert "track applied improvements" in added
    assert "add drift detector" in memory.backlog


def test_plan_self_evolution_caps_actions():
    planner = ImprovementPlanner()
    review = ArchitectureReview(
        diagnosis="ok",
        system_intent="self evolving",
        recommendations=[],
        backlog_items=[],
        self_evolution_actions=[
            PatchAction(path="a.py", operation="replace_file", description="1", new_content="a=1\n"),
            PatchAction(path="b.py", operation="replace_file", description="2", new_content="b=1\n"),
        ],
        execution_notes=["safe only"],
        risk_level="low",
    )

    planned = planner.plan_self_evolution(review, enabled=True, max_actions=1)

    assert len(planned.actions) == 1
    assert any("Capped self-evolution actions" in reason for reason in planned.reasons)
