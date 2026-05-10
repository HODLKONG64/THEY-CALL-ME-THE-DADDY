from __future__ import annotations

from the_daddy.models import CommandResult, RunRecord
from the_daddy.runtime.run_learning_ledger import build_run_learning_ledger_entry


def _record(*, run_id: str = "r1", mode: str = "repair", success: bool = True, patches=None, trace=None, rc: int = 0):
    rec = RunRecord(run_id=run_id, command="pytest -q")
    rec.selected_mode = mode
    rec.success = success
    rec.summary = "summary"
    rec.patches_applied = list(patches or [])
    rec.trace = list(trace or [])
    rec.verification = CommandResult(returncode=rc)
    return rec


def test_ledger_entry_created_for_successful_patch():
    rec = _record(
        success=True,
        patches=[{"path": "src/the_daddy/runtime/run_health.py"}],
        trace=[{"event": "patch_applied"}],
        rc=0,
    )
    entry = build_run_learning_ledger_entry(
        record=rec,
        upgrade_advice={"target_files": ["src/the_daddy/cli.py"], "tests_to_run": ["pytest -q"]},
        policy_route="safe",
        proposed_patches=[object()],
    )
    assert entry.outcome == "success_with_patch"
    assert entry.patch_count == 1


def test_ledger_entry_created_for_fake_noop_block():
    rec = _record(
        success=False,
        patches=[],
        trace=[{"event": "no_patch_blocker_recorded", "reason": "verification passed but no patch was applied"}],
        rc=0,
    )
    entry = build_run_learning_ledger_entry(
        record=rec,
        upgrade_advice={"target_files": ["src/the_daddy/cli.py"]},
        policy_route="safe",
        proposed_patches=[],
    )
    assert entry.outcome == "blocked_fake_noop"


def test_ledger_entry_created_for_advice_not_actionable():
    rec = _record(success=True, patches=[], trace=[], rc=0)
    entry = build_run_learning_ledger_entry(
        record=rec,
        upgrade_advice={"target_files": ["src/the_daddy/engine.py"]},
        policy_route="safe",
        proposed_patches=[],
        no_action_allowed=False,
    )
    assert entry.outcome == "advice_not_actionable"


def test_ledger_entry_created_for_verification_failure():
    rec = _record(success=False, patches=[], trace=[{"event": "patch_applied"}], rc=1)
    entry = build_run_learning_ledger_entry(
        record=rec,
        upgrade_advice={"target_files": ["src/the_daddy/engine.py"]},
        policy_route="safe",
        proposed_patches=[object()],
    )
    assert entry.outcome == "verification_failed"


def test_ledger_entry_created_for_clean_no_action():
    rec = _record(success=True, patches=[], trace=[], rc=0, mode="architecture")
    entry = build_run_learning_ledger_entry(
        record=rec,
        upgrade_advice={"target_files": [], "recommended_next_step": "no_action"},
        policy_route="safe",
        proposed_patches=[],
        no_action_allowed=True,
    )
    assert entry.outcome == "clean_no_action"


def test_ledger_entry_sanitizes_record_command_in_tests_run():
    rec = _record(success=True, patches=[], trace=[], rc=0)
    rec.command = "pytest -q OPENAI_API_KEY=sk-test-secret Authorization: Bearer sk-test-secret GITHUB_TOKEN=ghp_testsecret"
    entry = build_run_learning_ledger_entry(
        record=rec,
        upgrade_advice={"target_files": [], "recommended_next_step": "no_action"},
        policy_route="safe",
        proposed_patches=[],
        no_action_allowed=True,
    )
    blob = " ".join(entry.tests_run)
    assert "sk-test-secret" not in blob
    assert "ghp_testsecret" not in blob
    assert "Authorization: Bearer" not in blob
    assert "OPENAI_API_KEY=[REDACTED_SECRET]" in blob
    assert "GITHUB_TOKEN=[REDACTED_TOKEN]" in blob
