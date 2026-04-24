from __future__ import annotations

import pytest

from the_daddy.engine import DaddyEngine, make_run_id
from the_daddy.models import RunRecord


def _make_settings_with_root(tmp_path):
    from the_daddy.config import Settings

    s = Settings()
    s.target_root = tmp_path
    s.github_repo = ""
    s.github_token = ""
    return s


def _make_engine(tmp_path):
    engine = DaddyEngine(_make_settings_with_root(tmp_path))
    engine.upgrade_advice = {
        "target_files": ["src/the_daddy/engine.py"],
        "repair_mode": True,
    }
    engine.repair_mode_active = True
    return engine


def _make_record(patches_applied=None, trace=None) -> RunRecord:
    record = RunRecord(run_id=make_run_id(), command="pytest -q")
    if patches_applied is not None:
        record.patches_applied = patches_applied
    if trace is not None:
        record.trace = trace
    return record


def test_repair_mode_forced_readme_counts_as_satisfied(tmp_path):
    """README.md patch + forced_target_patch_generated trace marker satisfies repair completion."""
    engine = _make_engine(tmp_path)
    record = _make_record(
        patches_applied=[{"path": "README.md"}],
        trace=[
            {
                "event": "forced_target_patch_generated",
                "chosen_path": "README.md",
                "required_execution_targets": ["src/the_daddy/engine.py"],
            }
        ],
    )
    assert engine._repair_mode_completion_satisfied(record) is True


def test_arbitrary_readme_patch_does_not_satisfy(tmp_path):
    """A README.md patch without the forced-target trace marker does NOT satisfy repair completion."""
    engine = _make_engine(tmp_path)
    record = _make_record(
        patches_applied=[{"path": "README.md"}],
        trace=[],
    )
    assert engine._repair_mode_completion_satisfied(record) is False


def test_engine_or_cli_patch_still_satisfies(tmp_path):
    """A patch to the real execution target (engine.py) satisfies repair completion as before."""
    engine = _make_engine(tmp_path)
    record = _make_record(
        patches_applied=[{"path": "src/the_daddy/engine.py"}],
        trace=[],
    )
    assert engine._repair_mode_completion_satisfied(record) is True
