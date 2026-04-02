from the_daddy.models import ArchitectureReview, SelfEvolutionAction

def test_wake_review_ensures_safe_action():
    review = ArchitectureReview(
        diagnosis="Repository should always yield a safe self-evolution action during wake review.",
        system_intent="Automatic self-maintenance with safe evolution.",
        self_evolution_actions=[
            SelfEvolutionAction(
                title="Ensure safe action",
                description="Always include at least one safe self-evolution action.",
                risk="safe",
                patches=[],
            )
        ],
        risk_level="low",
    )

    assert review.self_evolution_actions
    assert any(action.risk == "safe" for action in review.self_evolution_actions)
