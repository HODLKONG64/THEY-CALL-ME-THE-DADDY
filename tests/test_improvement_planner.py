from the_daddy.agents.improvement_planner import ImprovementPlanner
from the_daddy.models import ArchitectureReview


def test_plan_self_evolution_keeps_valid_patches_from_mixed_dict_action_payload() -> None:
    planner = ImprovementPlanner()
    review = ArchitectureReview(
        diagnosis="normalize mixed payloads",
        system_intent="bounded maintenance",
        strengths=[],
        weaknesses=[],
        recommendations=[],
        backlog_items=[],
        self_evolution_actions=[
            {
                "title": "Keep valid patch",
                "description": "Drop malformed patch entries but retain safe valid ones.",
                "risk": "safe",
                "patches": [
                    {
                        "path": "docs/ARCHITECTURE.md",
                        "operation": "replace_file",
                        "new_content": "# ok\n",
                        "pattern": None,
                        "replacement": None,
                        "description": "valid patch",
                    },
                    {
                        "path": "",
                        "operation": "replace_file",
                        "new_content": "ignored",
                        "pattern": None,
                        "replacement": None,
                        "description": "invalid empty path",
                    },
                    {
                        "path": "docs/BAD.md",
                        "operation": "not_real",
                        "new_content": "ignored",
                        "pattern": None,
                        "replacement": None,
                        "description": "invalid operation",
                    },
                    "not a patch",
                ],
            }
        ],
        build_actions=[],
        architecture_plans=[],
        execution_notes=[],
        risk_level="low",
    )

    planned = planner.plan_self_evolution(review=review, enabled=True, max_actions=3)

    assert planned.enabled is True
    assert planned.reasons == []
    assert len(planned.actions) == 1
    assert planned.actions[0].title == "Keep valid patch"
    assert len(planned.actions[0].patches) == 1
    assert planned.actions[0].patches[0].path == "docs/ARCHITECTURE.md"
