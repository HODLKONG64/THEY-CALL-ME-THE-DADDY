from the_daddy.models import ArchitectureReview, SelfEvolutionAction


def test_architecture_review_includes_safe_self_evolution_action():
    review = ArchitectureReview(
        diagnosis='Ensure at least one safe self-evolution action.',
        system_intent='Bounded wake-review and repair system.',
        self_evolution_actions=[
            SelfEvolutionAction(
                title='Document invariant',
                description='Maintain at least one safe self-evolution action.',
                risk='safe',
                patches=[]
            )
        ],
        risk_level='low'
    )

    assert review.self_evolution_actions
    assert any(action.risk == 'safe' for action in review.self_evolution_actions)
