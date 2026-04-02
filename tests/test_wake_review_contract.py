from src.the_daddy.models import ArchitectureReview, SelfEvolutionAction

def test_wake_review_contract():
    review = ArchitectureReview(
        diagnosis='Ensure at least one safe action',
        system_intent='Bounded self-evolution',
        strengths=[],
        weaknesses=[],
        recommendations=[],
        backlog_items=[],
        self_evolution_actions=[SelfEvolutionAction(title='Test Action', description='Safe action', risk='safe', patches=[])],
        build_actions=[],
        architecture_plans=[],
        execution_notes=[],
        risk_level='low'
    )
    assert review.self_evolution_actions
    assert any(action.risk == 'safe' for action in review.self_evolution_actions)
