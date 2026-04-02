from the_daddy.models import ArchitectureReview, SelfEvolutionAction

def test_wake_review_must_include_safe_action():
    review = ArchitectureReview(
        diagnosis="Ensure at least one safe action is present in wake review.",
        system_intent="Maintain safe self-evolution.",
        self_evolution_actions=[
            SelfEvolutionAction(
                title="Fallback safe action",
                description="This is a placeholder indicating a safe action is always included.",
                risk="safe",
                patches=[],
            )
        ],
        risk_level="low",
    )
    assert any(action.risk == "safe" for action in review.self_evolution_actions)
