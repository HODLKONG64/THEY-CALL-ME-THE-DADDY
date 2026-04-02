def test_wake_review_contains_safe_action():
    review = ArchitectureReview(...)
    assert any(action.risk == 'safe' for action in review.self_evolution_actions)