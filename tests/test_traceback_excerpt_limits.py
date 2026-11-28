from the_daddy.runtime.error_digest import summarize_traceback_excerpt


TRACEBACK_TEXT = """
Traceback (most recent call last):
  File \"app.py\", line 10, in <module>
    main()
ValueError: boom
"""


def test_summarize_traceback_excerpt_returns_empty_excerpt_for_zero_limit() -> None:
    summary = summarize_traceback_excerpt(TRACEBACK_TEXT, max_lines=0)

    assert summary == {
        "line_count": 4,
        "excerpt": [],
        "last_line": "",
    }


def test_summarize_traceback_excerpt_returns_empty_excerpt_for_negative_limit() -> None:
    summary = summarize_traceback_excerpt(TRACEBACK_TEXT, max_lines=-3)

    assert summary == {
        "line_count": 4,
        "excerpt": [],
        "last_line": "",
    }


def test_summarize_traceback_excerpt_preserves_positive_limit_behavior() -> None:
    summary = summarize_traceback_excerpt(TRACEBACK_TEXT, max_lines=2)

    assert summary == {
        "line_count": 4,
        "excerpt": [
            '    main()',
            'ValueError: boom',
        ],
        "last_line": 'ValueError: boom',
    }
