from __future__ import annotations

import json
from pathlib import Path

from the_daddy.config import Settings
from the_daddy.memory import r2_store as r2_store_module
from the_daddy.memory.r2_store import R2Store
from the_daddy.memory.repository import MemoryRepository
from the_daddy.models import RunLearningLedgerEntry


def _entry(run_id: str, *, outcome: str = "clean_no_action", blocked_reason: str = "") -> RunLearningLedgerEntry:
    return RunLearningLedgerEntry(
        run_id=run_id,
        selected_mode="repair",
        outcome=outcome,
        subsystem="engine",
        blocked_reason=blocked_reason,
        files_involved=["src/the_daddy/cli.py"] if blocked_reason else [],
        avoid_next_time=[blocked_reason] if blocked_reason else [],
        what_worked=["applied_patches=1"] if outcome == "success_with_patch" else [],
    )


def test_memory_state_backward_compatible_without_ledger_field():
    repo = MemoryRepository(store=None)
    state = repo._coerce_state({"schema_version": "2.0", "runs": []})
    assert state.run_learning_ledger == []


def test_memory_repository_saves_and_reloads_learning_ledger(tmp_path: Path):
    settings = Settings(
        target_root=tmp_path,
        local_state_dir=tmp_path / "local",
        r2_endpoint_url="",
        r2_access_key_id="",
        r2_secret_access_key="",
        r2_bucket="",
    )
    store = R2Store(settings)
    repo = MemoryRepository(store)
    repo.add_run_learning_entry(_entry("r1", outcome="success_with_patch"))
    repo.add_run_learning_entry(_entry("r2", outcome="blocked_fake_noop", blocked_reason="verification passed but no patch was applied"))

    repo2 = MemoryRepository(store)
    rows = repo2.latest_run_learning_entries(limit=10)
    assert len(rows) >= 2
    assert rows[-1].outcome == "blocked_fake_noop"


def test_r2_local_fallback_persists_learning_ledger(tmp_path: Path):
    settings = Settings(
        target_root=tmp_path,
        local_state_dir=tmp_path / "state",
        memory_file_name="ledger.json",
        r2_endpoint_url="",
        r2_access_key_id="",
        r2_secret_access_key="",
        r2_bucket="",
    )
    repo = MemoryRepository(R2Store(settings))
    repo.add_run_learning_entry(_entry("r-local", outcome="advice_not_actionable"))

    memory_path = settings.local_state_dir / settings.memory_file_name
    payload = json.loads(memory_path.read_text(encoding="utf-8"))
    assert payload["run_learning_ledger"][-1]["outcome"] == "advice_not_actionable"


def test_learning_summary_includes_recurring_blockers():
    repo = MemoryRepository(store=None)
    repo.add_run_learning_entry(_entry("r1", outcome="blocked_fake_noop", blocked_reason="verification passed but no patch was applied"))
    repo.add_run_learning_entry(_entry("r2", outcome="blocked_fake_noop", blocked_reason="verification passed but no patch was applied"))
    repo.add_run_learning_entry(_entry("r3", outcome="success_with_patch"))

    summary = repo.summarize_recent_learning(limit=10)
    assert summary["recurring_blockers"][0]["blocked_reason"] == "verification passed but no patch was applied"
    assert summary["recurring_blockers"][0]["count"] >= 2


def test_r2_write_failure_keeps_local_persistence(tmp_path: Path, monkeypatch):
    class _FailingClient:
        def put_object(self, **_kwargs):
            raise RuntimeError("network failure")

        def get_object(self, **_kwargs):
            raise RuntimeError("not used")

    monkeypatch.setattr(r2_store_module.boto3, "client", lambda *args, **kwargs: _FailingClient())
    settings = Settings(
        target_root=tmp_path,
        local_state_dir=tmp_path / "local",
        memory_file_name="mem.json",
        r2_endpoint_url="https://example.invalid",
        r2_access_key_id="key",
        r2_secret_access_key="secret",
        r2_bucket="bucket",
    )
    store = R2Store(settings)
    repo = MemoryRepository(store)
    repo.add_run_learning_entry(_entry("r-r2-fail", outcome="success_with_patch"))

    saved = json.loads((settings.local_state_dir / settings.memory_file_name).read_text(encoding="utf-8"))
    assert saved["run_learning_ledger"][-1]["run_id"] == "r-r2-fail"


def test_corrupted_ledger_entries_are_ignored_safely():
    raw = {
        "schema_version": "3.0",
        "run_learning_ledger": [
            {"run_id": "ok", "outcome": "clean_no_action"},
            {"run_id": "bad", "outcome": {"not": "a string"}},
            "junk",
        ],
    }
    repo = MemoryRepository(store=None)
    state = repo._coerce_state(raw)
    assert len(state.run_learning_ledger) == 1
    assert state.run_learning_ledger[0].run_id == "ok"


def test_actionability_stats_separate_success_from_failures():
    repo = MemoryRepository(store=None)
    outcomes = [
        "verification_failed",
        "attempted_patch_failed",
        "policy_rejected",
        "git_pr_lane_failed",
        "success_with_patch",
        "clean_no_action",
        "advice_not_actionable",
        "blocked_fake_noop",
    ]
    for idx, outcome in enumerate(outcomes):
        entry = _entry(f"r{idx}", outcome=outcome)
        if outcome in {"attempted_patch_failed", "success_with_patch"}:
            entry.attempted_patch_count = 1
        repo.add_run_learning_entry(entry)

    stats = repo.advice_actionability_stats()
    assert stats["total"] == 8
    assert stats["advice_actionable_count"] == 2
    assert stats["verified_progress_count"] == 1
    assert stats["clean_no_action_count"] == 1
    assert stats["blocked_or_failed_count"] == 5
    assert stats["advice_not_actionable_count"] == 1
    assert stats["fake_noop_blocked_count"] == 1
