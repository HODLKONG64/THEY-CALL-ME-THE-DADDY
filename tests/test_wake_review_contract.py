from the_daddy.models import ArchitectureReview, SelfEvolutionAction


def test_architecture_review_includes_evolution_action():
    review = ArchitectureReview(
        diagnosis="Ensure wake review outputs at least one self-evolution action.",
        system_intent="Bounded self-healing and evolving system.",
        self_evolution_actions=[
            SelfEvolutionAction(
                title="Validate action presence",
                description="Check for at least one safe self-evolution action.",
                risk="safe",
                patches=[],
            )
        ],
        risk_level="low",
    )

    assert review.self_evolution_actions
    assert any(action.risk == "safe" for action in review.self_evolution_actions)
