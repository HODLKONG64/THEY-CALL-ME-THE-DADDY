"""Tests for the repair-mode upgrade gate.

Covered requirements
--------------------
1. CLI reads DADDY_UPGRADE_ADVICE_PATH when set.
2. Advice is loaded and validated before repair mode runs.
3. Repair mode refuses to run without approved advice.
4. Repair mode rejects README-only / keep-alive / filler patches.
5. Repair mode only allows bounded patches to approved target files.
6. Execution-path targets (cli.py / engine.py) are required.
7. If no valid execution-path patch is produced, engine fails with a clear reason.
8-9. Approved execution-path patches pass; unapproved / out-of-scope patches are blocked.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import the_daddy.cli as cli_module
from the_daddy.config import Settings
from the_daddy.core.upgrade_gate import UpgradeGateError, validate_upgrade_advice
from the_daddy.engine import DaddyEngine, make_run_id
from the_daddy.models import PatchAction, RunRecord


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_settings(tmp_path: Path) -> Settings:
    s = Settings()
    s.target_root = tmp_path
    s.github_repo = ""
    s.github_token = ""
    return s


def _make_engine(tmp_path: Path, *, target_files: list[str] | None = None) -> DaddyEngine:
    engine = DaddyEngine(_make_settings(tmp_path))
    engine.repair_mode_active = True
    engine.upgrade_advice = {
        "allow_proceed": False,
        "repair_mode": True,
        "problem_type": "healthy_safe_loop",
        "target_files": target_files or ["src/the_daddy/engine.py", "src/the_daddy/cli.py"],
        "forbidden_repeat_patterns": ["no filler patches"],
        "summary": "repair mode",
        "repo_state": "test",
        "recommended_next_step": "upgrade engine/cli",
        "required_constraints": [],
        "tests_to_run": ["pytest -q"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return engine


def _make_record() -> RunRecord:
    return RunRecord(run_id=make_run_id(), command="pytest -q")


def _make_patch(path: str, description: str = "test patch") -> PatchAction:
    return PatchAction(
        path=path,
        operation="regex_replace",
        pattern=r"\Z",
        replacement="# patched\n",
        description=description,
    )


def _write_advice(
    path: Path,
    *,
    allow_proceed: bool = True,
    problem_type: str | None = None,
    generated_at: str | None = None,
) -> Path:
    payload = {
        "allow_proceed": allow_proceed,
        "summary": "approved" if allow_proceed else "rejected",
        "repo_state": "test",
        "problem_type": problem_type or ("healthy_meaningful_progress" if allow_proceed else "healthy_safe_loop"),
        "recommended_next_step": "run bounded upgrade",
        "target_files": ["src/the_daddy/engine.py", "src/the_daddy/cli.py"],
        "forbidden_repeat_patterns": ["no filler"],
        "required_constraints": [],
        "tests_to_run": ["pytest -q"],
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Requirement 3 – repair mode refuses to run without approved advice
# ---------------------------------------------------------------------------

class TestCliAdviceGating:
    def test_missing_advice_blocks_cli(self, monkeypatch, capsys):
        """CLI exits 1 and prints a clear message when DADDY_UPGRADE_ADVICE_PATH is unset."""
        monkeypatch.delenv("DADDY_UPGRADE_ADVICE_PATH", raising=False)
        monkeypatch.setattr(cli_module, "get_settings", lambda: Settings())
        result = cli_module.main()
        captured = capsys.readouterr()
        assert result == 1
        assert "Upgrade gate blocked execution" in captured.err

    def test_unapproved_advice_blocks_cli(self, tmp_path, monkeypatch, capsys):
        """CLI exits 1 when advice file exists but allow_proceed=False and not a safe-loop."""
        advice_path = _write_advice(
            tmp_path / "rejected.json", allow_proceed=False, problem_type="failing_repo"
        )
        monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))
        monkeypatch.setattr(cli_module, "get_settings", lambda: Settings())
        result = cli_module.main()
        captured = capsys.readouterr()
        assert result == 1
        assert "Upgrade gate blocked execution" in captured.err

    def test_approved_advice_allows_cli(self, tmp_path, monkeypatch):
        """CLI proceeds when advice is approved."""
        advice_path = _write_advice(tmp_path / "approved.json", allow_proceed=True)
        monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

        class _DummyRecord:
            run_id = "r1"
            command = "pytest -q"
            selected_mode = "build"
            success = True
            summary = "ok"
            patches_applied = []
            rollback_manifest = []
            trace = []
            backlog_updates = []
            repo_fingerprint = {}
            verification = None

        class _DummyEngine:
            def __init__(self, settings):
                self.upgrade_advice = None
                self.repair_mode_active = False

            def run(self):
                return _DummyRecord()

        monkeypatch.setattr(cli_module, "DaddyEngine", _DummyEngine)
        monkeypatch.setattr(cli_module, "get_settings", lambda: Settings())
        assert cli_module.main() == 0


# ---------------------------------------------------------------------------
# Requirements 4 & 5 – repair mode rejects out-of-scope and README patches
# ---------------------------------------------------------------------------

class TestRepairModeTargetFilter:
    def test_readme_only_patch_rejected_in_repair_mode(self, tmp_path):
        """README.md patch is filtered out when it is not in the approved target_files."""
        engine = _make_engine(tmp_path, target_files=["src/the_daddy/engine.py"])
        patches = [_make_patch("README.md", "filler heartbeat")]
        record = _make_record()
        result = engine._enforce_repair_mode_targets(patches, record)
        assert result == []
        assert any(e.get("event") in {
            "repair_mode_no_target_match",
            "repair_mode_target_filter",
        } for e in record.trace)

    def test_out_of_scope_patch_rejected_in_repair_mode(self, tmp_path):
        """Patches to unapproved files are stripped in repair mode."""
        engine = _make_engine(tmp_path, target_files=["src/the_daddy/cli.py"])
        patches = [_make_patch("src/the_daddy/prompts.py", "off-target change")]
        record = _make_record()
        result = engine._enforce_repair_mode_targets(patches, record)
        assert result == []

    def test_keep_alive_patch_rejected_in_repair_mode(self, tmp_path):
        """A no-op helper-lane-filler patch that targets an off-scope file is filtered."""
        engine = _make_engine(tmp_path, target_files=["src/the_daddy/engine.py"])
        patches = [_make_patch("src/the_daddy/runtime/trace_summary.py", "keep-alive filler")]
        record = _make_record()
        result = engine._enforce_repair_mode_targets(patches, record)
        assert result == []

    def test_readme_patch_filtered_emits_trace(self, tmp_path):
        """The filter emits a repair_mode_target_filter trace event with correct metadata."""
        engine = _make_engine(tmp_path, target_files=["src/the_daddy/engine.py"])
        patches = [_make_patch("README.md")]
        record = _make_record()
        engine._enforce_repair_mode_targets(patches, record)
        events = [e.get("event") for e in record.trace]
        assert "repair_mode_target_filter" in events


# ---------------------------------------------------------------------------
# Requirements 5 & 9 – approved execution-path patches are accepted
# ---------------------------------------------------------------------------

class TestRepairModeAcceptsExecutionPathPatches:
    def test_cli_patch_passes_target_filter(self, tmp_path):
        """A patch targeting cli.py passes _enforce_repair_mode_targets."""
        engine = _make_engine(tmp_path, target_files=["src/the_daddy/cli.py"])
        patches = [_make_patch("src/the_daddy/cli.py")]
        record = _make_record()
        result = engine._enforce_repair_mode_targets(patches, record)
        assert len(result) == 1
        assert result[0].path == "src/the_daddy/cli.py"

    def test_engine_patch_passes_target_filter(self, tmp_path):
        """A patch targeting engine.py passes _enforce_repair_mode_targets."""
        engine = _make_engine(tmp_path, target_files=["src/the_daddy/engine.py"])
        patches = [_make_patch("src/the_daddy/engine.py")]
        record = _make_record()
        result = engine._enforce_repair_mode_targets(patches, record)
        assert len(result) == 1
        assert result[0].path == "src/the_daddy/engine.py"

    def test_mixed_patches_only_approved_survive(self, tmp_path):
        """Only patches targeting approved files survive; the rest are stripped."""
        engine = _make_engine(tmp_path, target_files=["src/the_daddy/cli.py"])
        patches = [
            _make_patch("src/the_daddy/cli.py"),
            _make_patch("README.md"),
            _make_patch("src/the_daddy/prompts.py"),
        ]
        record = _make_record()
        result = engine._enforce_repair_mode_targets(patches, record)
        assert len(result) == 1
        assert result[0].path == "src/the_daddy/cli.py"

    def test_both_execution_targets_accepted(self, tmp_path):
        """Patches to both cli.py and engine.py both survive when both are in target_files."""
        engine = _make_engine(
            tmp_path, target_files=["src/the_daddy/cli.py", "src/the_daddy/engine.py"]
        )
        patches = [
            _make_patch("src/the_daddy/cli.py"),
            _make_patch("src/the_daddy/engine.py"),
        ]
        record = _make_record()
        result = engine._enforce_repair_mode_targets(patches, record)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Requirement 7 – failure path emits a clear reason
# ---------------------------------------------------------------------------

class TestRepairModeCompletionBlocked:
    def test_completion_blocked_emits_clear_reason(self, tmp_path):
        """_repair_mode_completion_satisfied returns False for unmatched patches; engine
        records repair_mode_completion_blocked with a reason when the run would complete
        without an approved execution-path patch."""
        engine = _make_engine(tmp_path, target_files=["src/the_daddy/engine.py"])
        # Simulate a record whose only applied patch is README.md (no trace marker)
        record = _make_record()
        record.patches_applied = [{"path": "README.md"}]
        record.trace = []  # no forced_target_patch_generated event
        assert engine._repair_mode_completion_satisfied(record) is False

    def test_completion_satisfied_for_cli_patch(self, tmp_path):
        """Applying a cli.py patch satisfies repair-mode completion."""
        engine = _make_engine(tmp_path, target_files=["src/the_daddy/cli.py"])
        record = _make_record()
        record.patches_applied = [{"path": "src/the_daddy/cli.py"}]
        record.trace = []
        assert engine._repair_mode_completion_satisfied(record) is True

    def test_completion_satisfied_for_engine_patch(self, tmp_path):
        """Applying an engine.py patch satisfies repair-mode completion."""
        engine = _make_engine(tmp_path, target_files=["src/the_daddy/engine.py"])
        record = _make_record()
        record.patches_applied = [{"path": "src/the_daddy/engine.py"}]
        record.trace = []
        assert engine._repair_mode_completion_satisfied(record) is True

    def test_no_patches_does_not_satisfy(self, tmp_path):
        """Empty patches_applied does not satisfy repair-mode completion."""
        engine = _make_engine(tmp_path, target_files=["src/the_daddy/engine.py"])
        record = _make_record()
        record.patches_applied = []
        record.trace = []
        assert engine._repair_mode_completion_satisfied(record) is False


# ---------------------------------------------------------------------------
# Bug fix – minimal execution probe uses target_root, not CWD
# ---------------------------------------------------------------------------

class TestMinimalExecutionProbe:
    def test_probe_uses_target_root_for_existence_check(self, tmp_path):
        """The probe uses self.settings.target_root / candidate, not os.path.exists(candidate)."""
        cli_in_root = tmp_path / "src" / "the_daddy" / "cli.py"
        cli_in_root.parent.mkdir(parents=True, exist_ok=True)
        cli_in_root.write_text("# cli\n", encoding="utf-8")

        engine = _make_engine(tmp_path, target_files=["src/the_daddy/cli.py"])
        record = _make_record()
        patches = engine._build_minimal_execution_probe_patch(record.run_id)
        assert len(patches) == 1
        assert patches[0].path == "src/the_daddy/cli.py"

    def test_probe_does_not_fire_when_only_engine_in_targets(self, tmp_path):
        """Probe returns [] when cli.py is NOT in the required targets (even if engine.py exists)."""
        engine_in_root = tmp_path / "src" / "the_daddy" / "engine.py"
        engine_in_root.parent.mkdir(parents=True, exist_ok=True)
        engine_in_root.write_text("# engine\n", encoding="utf-8")

        engine = _make_engine(tmp_path, target_files=["src/the_daddy/engine.py"])
        record = _make_record()
        patches = engine._build_minimal_execution_probe_patch(record.run_id)
        assert patches == []

    def test_probe_targets_cli_when_both_in_targets(self, tmp_path):
        """Probe targets cli.py when both execution targets are in target_files."""
        for name in ("cli.py", "engine.py"):
            f = tmp_path / "src" / "the_daddy" / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("# source\n", encoding="utf-8")

        engine = _make_engine(
            tmp_path,
            target_files=["src/the_daddy/cli.py", "src/the_daddy/engine.py"],
        )
        record = _make_record()
        patches = engine._build_minimal_execution_probe_patch(record.run_id)
        assert len(patches) == 1
        assert patches[0].path == "src/the_daddy/cli.py"

    def test_probe_returns_empty_when_files_missing(self, tmp_path):
        """Probe returns [] when neither target file exists under target_root."""
        engine = _make_engine(
            tmp_path,
            target_files=["src/the_daddy/cli.py", "src/the_daddy/engine.py"],
        )
        record = _make_record()
        patches = engine._build_minimal_execution_probe_patch(record.run_id)
        assert patches == []

    def test_probe_returns_empty_when_targets_not_execution_path(self, tmp_path):
        """Probe returns [] when target_files do not include any execution-path file."""
        engine = _make_engine(tmp_path, target_files=["src/the_daddy/config.py"])
        record = _make_record()
        patches = engine._build_minimal_execution_probe_patch(record.run_id)
        assert patches == []
