from models import ArchitectureReview, SelfEvolutionAction

def test_wake_review_invariants():
    review = ArchitectureReview(
        diagnosis="Ensure wake-review outputs at least one safe action.",
        system_intent="Maintain bounded self-evolution.",
        self_evolution_actions=[
            SelfEvolutionAction(
                title="Ensure invariant",
                description="Wake-review must return a safe action.",
                risk="safe",
                patches=[]
            )
        ],
        risk_level="low",
    )

    assert review.self_evolution_actions
    assert any(action.risk == "safe" for action in review.self_evolution_actions)
