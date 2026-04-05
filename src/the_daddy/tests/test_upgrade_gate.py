from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import the_daddy.cli as cli
from the_daddy.config import Settings
from the_daddy.core.upgrade_gate import (
    UpgradeGateError,
    validate_upgrade_advice,
    validate_upgrade_gate_for_settings,
)


def _write_advice(
    path: Path,
    *,
    allow_proceed: bool = True,
    generated_at: str | None = None,
    problem_type: str | None = None,
) -> Path:
    payload = {
        "allow_proceed": allow_proceed,
        "summary": "approved" if allow_proceed else "rejected",
        "repo_state": "test_repo_state",
        "problem_type": problem_type or ("healthy_meaningful_progress" if allow_proceed else "healthy_safe_loop"),
        "recommended_next_step": "run bounded upgrade",
        "target_files": ["src/the_daddy/engine.py"],
        "forbidden_repeat_patterns": ["no filler patches"],
        "required_constraints": ["small changes only"],
        "tests_to_run": ["pytest -q"],
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_validate_upgrade_advice_accepts_approved_file(tmp_path, monkeypatch):
    advice_path = _write_advice(tmp_path / "approved.json")
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))
    advice = validate_upgrade_advice()
    assert advice["allow_proceed"] is True


def test_validate_upgrade_advice_rejects_missing_file(monkeypatch):
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", "/tmp/does-not-exist.json")
    with pytest.raises(UpgradeGateError):
        validate_upgrade_advice()


def test_validate_upgrade_advice_rejects_rejected_file(tmp_path, monkeypatch):
    advice_path = _write_advice(tmp_path / "rejected.json", allow_proceed=False, problem_type="failing_repo")
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))
    with pytest.raises(UpgradeGateError):
        validate_upgrade_advice()


def test_validate_upgrade_advice_rejects_stale_file(tmp_path, monkeypatch):
    stale = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
    advice_path = _write_advice(tmp_path / "stale.json", generated_at=stale)
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))
    with pytest.raises(UpgradeGateError):
        validate_upgrade_advice()


def test_validate_upgrade_gate_enters_repair_mode_for_safe_loop(tmp_path, monkeypatch):
    advice_path = _write_advice(tmp_path / "repair.json", allow_proceed=False, problem_type="healthy_safe_loop")
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))
    result = validate_upgrade_gate_for_settings(Settings())
    assert result["repair_mode"] is True
    assert result["allow_proceed"] is False


def test_cli_blocks_when_upgrade_advice_missing(monkeypatch, capsys):
    monkeypatch.delenv("DADDY_UPGRADE_ADVICE_PATH", raising=False)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings())
    monkeypatch.setattr(cli.sys, "argv", ["cli", "run"])
    result = cli.main()
    captured = capsys.readouterr()
    assert result == 1
    assert "Upgrade gate blocked execution" in captured.err


def test_cli_blocks_when_upgrade_advice_rejected_for_non_safe_loop(tmp_path, monkeypatch, capsys):
    advice_path = _write_advice(tmp_path / "rejected.json", allow_proceed=False, problem_type="failing_repo")
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))
    monkeypatch.setattr(cli, "get_settings", lambda: Settings())
    monkeypatch.setattr(cli.sys, "argv", ["cli", "run"])
    result = cli.main()
    captured = capsys.readouterr()
    assert result == 1
    assert "Upgrade gate blocked execution" in captured.err


def test_cli_allows_run_when_upgrade_advice_approved(tmp_path, monkeypatch):
    advice_path = _write_advice(tmp_path / "approved.json", allow_proceed=True)
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

    class DummyRecord:
        run_id = "test-run-1"
        command = "pytest -q"
        selected_mode = "build"
        success = True
        summary = "Success"
        patches_applied = []
        rollback_manifest = []
        trace = []
        backlog_updates = []
        repo_fingerprint = {}
        verification = None
        self_evolution = None
        architecture_review = None

    class DummyEngine:
        def __init__(self, settings):
            self.settings = settings
            self.upgrade_advice = None
            self.repair_mode_active = False

        def run(self):
            return DummyRecord()

    monkeypatch.setattr(cli, "DaddyEngine", DummyEngine)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings())
    monkeypatch.setattr(cli.sys, "argv", ["cli", "run"])

    result = cli.main()
    assert result == 0


def test_cli_allows_run_in_repair_mode_for_safe_loop(tmp_path, monkeypatch):
    advice_path = _write_advice(tmp_path / "repair.json", allow_proceed=False, problem_type="healthy_safe_loop")
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

    class DummyRecord:
        run_id = "test-run-2"
        command = "pytest -q"
        selected_mode = "build"
        success = True
        summary = "Success"
        patches_applied = []
        rollback_manifest = []
        trace = []
        backlog_updates = []
        repo_fingerprint = {}
        verification = None
        self_evolution = None
        architecture_review = None

    class DummyEngine:
        def __init__(self, settings):
            self.settings = settings
            self.upgrade_advice = None
            self.repair_mode_active = False

        def run(self):
            return DummyRecord()

    monkeypatch.setattr(cli, "DaddyEngine", DummyEngine)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings())
    monkeypatch.setattr(cli.sys, "argv", ["cli", "run"])

    result = cli.main()
    assert result == 0
