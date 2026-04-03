from the_daddy.models import ArchitectureReview, SelfEvolutionAction

def test_wake_review_includes_safe_action():
    review = ArchitectureReview(
        diagnosis="Check that at least one safe self-evolution action is included.",
        system_intent="Ensure safety requirements are met.",
        self_evolution_actions=[
            SelfEvolutionAction(
                title="Safety Check",
                description="Verify inclusion of a safe action.",
                risk="safe",
                patches=[]
            )
        ],
        risk_level="low",
    )
    assert any(action.risk == "safe" for action in review.self_evolution_actions)