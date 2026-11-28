"""Disposable fixture for Issue #113. Never merge into main."""


def count_pending(total: int, completed: int) -> int:
    return total - completed


def test_counts_pending_items():
    assert count_pending(8, 3) == 5


def test_never_returns_a_negative_count():
    assert count_pending(2, 3) == 0
