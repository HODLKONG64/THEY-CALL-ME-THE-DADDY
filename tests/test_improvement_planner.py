from the_daddy.agents.improvement_planner import ImprovementPlanner
from the_daddy.models import ArchitectureReview


def test_normalize_self_evolution_actions_filters_invalid_patches_per_action_dict():
    planner = ImprovementPlanner()

    review = ArchitectureReview(
        diagnosis="Mixed patch payloads should be normalized safely.",
        system_intent="Bounded maintenance.",
        self_evolution_actions=[
            {
                "title": "Keep valid patches only",
                "description": "Malformed nested patch entries should be ignored.",
                "risk": "safe",
                "patches": [
                    {
                        "path": "docs/ARCHITECTURE.md",
                        "operation": "replace_file",
                        "new_content": "# Updated\n\nThis document describes the architecture in sufficient detail to pass the minimum content size guard.\n",
                        "pattern": None,
                        "replacement": None,
                        "description": "valid replace_file patch",
                    },
                    {
                        "path": "docs/ARCHITECTURE.md",
                        "operation": "replace_file",
                        "new_content": None,
                        "pattern": None,
                        "replacement": None,
                        "description": "invalid replace_file patch missing content",
                    },
                    {
                        "path": "src/the_daddy/agents/improvement_planner.py",
                        "operation": "regex_replace",
                        "new_content": None,
                        "pattern": "old",
                        "replacement": "new",
                        "description": "valid regex patch",
                    },
                    {
                        "path": "src/the_daddy/agents/improvement_planner.py",
                        "operation": "regex_replace",
                        "new_content": None,
                        "pattern": "old",
                        "replacement": None,
                        "description": "invalid regex patch missing replacement",
                    },
                    "not-a-patch",
                ],
            }
        ],
        risk_level="low",
    )

    planned = planner.plan_self_evolution(review, enabled=True, max_actions=3)

    assert planned.enabled is True
    assert planned.reasons == []
    assert len(planned.actions) == 1
    assert len(planned.actions[0].patches) == 2
    assert [patch.operation for patch in planned.actions[0].patches] == ["replace_file", "regex_replace"]
