from types import SimpleNamespace

from the_daddy.agents.improvement_planner import ImprovementPlanner
from the_daddy.models import ArchitectureReview, MemoryState, PatchAction, SelfEvolutionAction


def test_decide_mode_prefers_build_when_valid_safe_self_evolution_exists():
    planner = ImprovementPlanner()
    memory = MemoryState()
    review = ArchitectureReview(
        diagnosis="d",
        system_intent="i",
        self_evolution_actions=[
            SelfEvolutionAction(
                title="Add note",
                description="Safe doc update",
                risk="safe",
                patches=[
                    PatchAction(
                        path="README.md",
                        operation="replace_file",
                        new_content="# updated\n",
                        pattern=None,
                        replacement=None,
                        description="Update docs",
                    )
                ],
            )
        ],
        risk_level="low",
    )

    assert planner.decide_mode(memory, review) == "build"


def test_malformed_self_evolution_entries_do_not_trigger_build_mode_or_actions():
    planner = ImprovementPlanner()
    memory = MemoryState()
    malformed_action = SimpleNamespace(
        title="Looks valid",
        description="But contains malformed patches",
        risk="safe",
        patches=[SimpleNamespace(path="README.md", operation="replace_file")],
    )
    review = ArchitectureReview(
        diagnosis="d",
        system_intent="i",
        self_evolution_actions=[malformed_action],
        risk_level="low",
    )

    planned = planner.plan_self_evolution(review, enabled=True, max_actions=3)

    assert planned.actions == []
    assert planned.reasons == ["No valid safe actions found"]
    assert planner.decide_mode(memory, review) == "repair"
