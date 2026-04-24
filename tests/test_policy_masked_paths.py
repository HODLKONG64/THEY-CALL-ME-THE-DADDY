"""Tests for masked-path normalization in policy.py.

The_*** in a path segment is normalized to the_daddy before policy evaluation,
so that OpenAI-masked paths are treated identically to real repository paths.
"""
from the_daddy.models import PatchAction
from the_daddy.policy import classify_patch_risk, _normalize_masked_path


# ---------------------------------------------------------------------------
# Unit tests for the helper
# ---------------------------------------------------------------------------

def test_normalize_masked_path_replaces_the_masked():
    assert _normalize_masked_path("src/the_***/cli.py") == "src/the_daddy/cli.py"


def test_normalize_masked_path_leaves_unrelated_unchanged():
    assert _normalize_masked_path("src/other_***/cli.py") == "src/other_***/cli.py"


def test_normalize_masked_path_no_op_on_real_path():
    assert _normalize_masked_path("src/the_daddy/cli.py") == "src/the_daddy/cli.py"


# ---------------------------------------------------------------------------
# Scenario 1 – masked path treated identically to the real path
# ---------------------------------------------------------------------------

def _make_runtime_patch(path: str) -> PatchAction:
    """Return a patch targeting a safe runtime helper file at the given path."""
    return PatchAction(
        path=path,
        operation="regex_replace",
        description="minor fix",
        pattern="old",
        replacement="new",
    )


def test_masked_path_same_result_as_real_path():
    """src/the_***/runtime/trace_summary.py must yield the same policy result
    as src/the_daddy/runtime/trace_summary.py."""
    masked = classify_patch_risk([_make_runtime_patch("src/the_***/runtime/trace_summary.py")])
    real = classify_patch_risk([_make_runtime_patch("src/the_daddy/runtime/trace_summary.py")])

    assert masked.passed == real.passed
    assert masked.route == real.route


def test_masked_runtime_path_passes_policy():
    """A masked path pointing at an allowlisted runtime helper must pass."""
    result = classify_patch_risk([_make_runtime_patch("src/the_***/runtime/trace_summary.py")])
    assert result.passed
    assert result.route == "safe"


# ---------------------------------------------------------------------------
# Scenario 2 – real path continues to be handled correctly
# ---------------------------------------------------------------------------

def test_real_runtime_path_passes_policy():
    """The un-masked version of the same path must still pass."""
    result = classify_patch_risk([_make_runtime_patch("src/the_daddy/runtime/trace_summary.py")])
    assert result.passed
    assert result.route == "safe"


# ---------------------------------------------------------------------------
# Scenario 3 – unrelated masked patterns are NOT normalized and remain rejected
# ---------------------------------------------------------------------------

def test_unrelated_masked_path_not_normalized():
    """A path with a different masked pattern (no the_***) is not mapped to
    the_daddy.  To prove this, we use a protected-core file: if other_*** were
    silently mapped to the_daddy, the patch would be blocked; since it is not
    mapped to the_daddy, it does not match the protected path pattern and passes
    policy."""
    # The real path src/the_daddy/policy.py is a protected core file → blocked.
    real_protected = classify_patch_risk([_make_runtime_patch("src/the_daddy/policy.py")])
    assert not real_protected.passed, "src/the_daddy/policy.py must be blocked"

    # A path using a different masked segment must NOT be normalised to the_daddy.
    other_masked = classify_patch_risk([_make_runtime_patch("src/other_***/policy.py")])
    assert other_masked.passed, (
        "src/other_***/policy.py must not be mapped to the_daddy and should pass"
    )
