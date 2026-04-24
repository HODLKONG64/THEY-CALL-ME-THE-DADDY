from __future__ import annotations

import os

import pytest

from the_daddy.engine import CLI_PROBE_TARGET, DaddyEngine, make_run_id
from the_daddy.models import PatchAction, RunRecord


def _make_settings_with_root(tmp_path):
    from the_daddy.config import Settings

    s = Settings()
    s.target_root = tmp_path
    s.github_repo = ""
    s.github_token = ""
    return s


def _make_record(tmp_path) -> RunRecord:
    return RunRecord(run_id=make_run_id(), command="test")


def test_real_patch_targets_cli_py(tmp_path):
    """Patch must target cli.py."""
    cli_file = tmp_path / CLI_PROBE_TARGET
    cli_file.parent.mkdir(parents=True, exist_ok=True)
    cli_file.write_text("# cli\n", encoding="utf-8")

    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": [CLI_PROBE_TARGET], "repair_mode": True}

    record = _make_record(tmp_path)
    patches = engine._build_real_cli_improvement_patch(record)

    assert len(patches) == 1
    p = patches[0]
    assert isinstance(p, PatchAction)
    assert p.path == CLI_PROBE_TARGET


def test_real_patch_description(tmp_path):
    """Patch description must be 'Add safe CLI execution guard'."""
    cli_file = tmp_path / CLI_PROBE_TARGET
    cli_file.parent.mkdir(parents=True, exist_ok=True)
    cli_file.write_text("# cli\n", encoding="utf-8")

    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": [CLI_PROBE_TARGET], "repair_mode": True}

    record = _make_record(tmp_path)
    patches = engine._build_real_cli_improvement_patch(record)

    assert len(patches) == 1
    assert patches[0].description == "Add safe CLI execution guard"


def test_real_patch_returns_empty_when_cli_missing(tmp_path):
    """Returns empty list when cli.py does not exist on disk."""
    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": [CLI_PROBE_TARGET], "repair_mode": True}

    record = _make_record(tmp_path)
    patches = engine._build_real_cli_improvement_patch(record)

    assert patches == []


def test_probe_used_when_real_patch_unavailable(tmp_path, monkeypatch):
    """When cli.py does not exist, real patch is empty; probe is tried next."""
    # cli.py does NOT exist under target_root (so real patch returns [])
    # but os.path.exists returns True for CLI_PROBE_TARGET so probe returns a patch
    monkeypatch.setattr(os.path, "exists", lambda p: p == CLI_PROBE_TARGET)

    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": [CLI_PROBE_TARGET], "repair_mode": True}

    record = _make_record(tmp_path)

    # Real patch should be empty because target_root / CLI_PROBE_TARGET doesn't exist
    # (os.path.exists is monkeypatched to only return True for bare CLI_PROBE_TARGET string)
    real = engine._build_real_cli_improvement_patch(record)
    assert real == []

    # Probe should return a patch since os.path.exists(CLI_PROBE_TARGET) is True
    probe = engine._build_minimal_execution_probe_patch(record.run_id)
    assert len(probe) == 1
    assert probe[0].path == CLI_PROBE_TARGET


def test_real_patch_content(tmp_path):
    """Patch replacement contains DADDY_SAFE_GUARD marker."""
    cli_file = tmp_path / CLI_PROBE_TARGET
    cli_file.parent.mkdir(parents=True, exist_ok=True)
    cli_file.write_text("# cli\n", encoding="utf-8")

    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": [CLI_PROBE_TARGET], "repair_mode": True}

    record = _make_record(tmp_path)
    patches = engine._build_real_cli_improvement_patch(record)

    assert len(patches) == 1
    assert "DADDY_SAFE_GUARD" in patches[0].replacement
    assert patches[0].operation == "regex_replace"
    assert patches[0].pattern == r"\Z"
