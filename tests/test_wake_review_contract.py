from the_daddy.models import ArchitectureReview, SelfEvolutionAction

def test_wake_review_invariant():
    review = ArchitectureReview(
        diagnosis="Ensure at least one safe self-evolution action.",
        system_intent="Bounded self-maintenance.",
        self_evolution_actions=[
            SelfEvolutionAction(
                title="Invariant enforcement",
                description="Must have at least one safe action.",
                risk="safe",
                patches=[]
            )
        ],
        risk_level="low"
    )
    assert review.self_evolution_actions
    assert any(action.risk == "safe" for action in review.self_evolution_actions)
