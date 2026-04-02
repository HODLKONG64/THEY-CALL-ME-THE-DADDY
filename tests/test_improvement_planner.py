from the_daddy.agents.improvement_planner import ImprovementPlanner
from the_daddy.models import ArchitectureReview, MemoryState


def test_plan_self_evolution_accepts_dict_shaped_safe_actions():
    planner = ImprovementPlanner()
    review = ArchitectureReview(
        diagnosis="Normalize review payloads.",
        system_intent="Bounded self-maintenance.",
        strengths=[],
        weaknesses=[],
        recommendations=[],
        backlog_items=[],
        self_evolution_actions=[
            {
                "title": "Add planner guard",
                "description": "Normalize dict-shaped review actions safely.",
                "risk": "safe",
                "patches": [
                    {
                        "path": "docs/ARCHITECTURE.md",
                        "operation": "replace_file",
                        "new_content": "# note\n",
                        "pattern": None,
                        "replacement": None,
                        "description": "doc update",
                    }
                ],
            }
        ],
        build_actions=[],
        architecture_plans=[],
        execution_notes=[],
        risk_level="low",
    )

    planned = planner.plan_self_evolution(review, enabled=True, max_actions=3)

    assert planned.enabled is True
    assert len(planned.actions) == 1
    assert planned.actions[0].title == "Add planner guard"
    assert planned.actions[0].patches[0].path == "docs/ARCHITECTURE.md"


def test_decide_mode_uses_normalized_dict_shaped_self_evolution_actions():
    planner = ImprovementPlanner()
    memory = MemoryState()
    review = ArchitectureReview(
        diagnosis="Normalize review payloads.",
        system_intent="Bounded self-maintenance.",
        strengths=[],
        weaknesses=[],
        recommendations=[],
        backlog_items=[],
        self_evolution_actions=[
            {
                "title": "Add planner guard",
                "description": "Normalize dict-shaped review actions safely.",
                "risk": "safe",
                "patches": [
                    {
                        "path": "docs/ARCHITECTURE.md",
                        "operation": "replace_file",
                        "new_content": "# note\n",
                        "pattern": None,
                        "replacement": None,
                        "description": "doc update",
                    }
                ],
            }
        ],
        build_actions=[],
        architecture_plans=[],
        execution_notes=[],
        risk_level="low",
    )

    assert planner.decide_mode(memory, review) == "build"
