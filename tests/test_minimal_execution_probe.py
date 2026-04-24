from __future__ import annotations

import os

from the_daddy.engine import CLI_PROBE_TARGET, DaddyEngine, make_run_id
from the_daddy.models import PatchAction, RunRecord


def _make_settings_with_root(tmp_path):
    from the_daddy.config import Settings

    s = Settings()
    s.target_root = tmp_path
    s.github_repo = ""
    s.github_token = ""
    return s


def _make_run_id() -> str:
    return make_run_id()


def test_probe_generates_patch_for_cli_target(tmp_path, monkeypatch):
    target_dir = tmp_path / "src" / "the_daddy"
    target_dir.mkdir(parents=True)
    cli_file = target_dir / "cli.py"
    cli_file.write_text("# cli\n", encoding="utf-8")

    monkeypatch.setattr(os.path, "exists", lambda p: p == CLI_PROBE_TARGET)

    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": [CLI_PROBE_TARGET], "repair_mode": True}
    run_id = _make_run_id()

    patches = engine._build_minimal_execution_probe_patch(run_id)

    assert len(patches) == 1
    p = patches[0]
    assert isinstance(p, PatchAction)
    assert p.path == CLI_PROBE_TARGET
    assert p.operation == "regex_replace"
    assert p.pattern == r"\Z"
    assert f"# DADDY_REAL_REPAIR_PROBE: {run_id}" in (p.replacement or "")
    assert p.description == "Minimal real execution repair probe"


def test_probe_returns_empty_when_cli_not_in_targets(tmp_path):
    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    # engine.py is a valid execution target but not cli.py
    engine.upgrade_advice = {"target_files": ["src/the_daddy/engine.py"], "repair_mode": True}
    run_id = _make_run_id()

    patches = engine._build_minimal_execution_probe_patch(run_id)

    assert patches == []


def test_probe_returns_empty_when_no_required_targets(tmp_path):
    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    # upgrade_advice with no execution-path targets
    engine.upgrade_advice = {"target_files": ["README.md"], "repair_mode": True}
    run_id = _make_run_id()

    patches = engine._build_minimal_execution_probe_patch(run_id)

    assert patches == []


def test_probe_returns_empty_when_cli_file_missing(tmp_path, monkeypatch):
    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": [CLI_PROBE_TARGET], "repair_mode": True}
    run_id = _make_run_id()

    monkeypatch.setattr(os.path, "exists", lambda p: False)

    # cli.py is in targets but doesn't exist on disk
    patches = engine._build_minimal_execution_probe_patch(run_id)

    assert patches == []


def test_probe_returns_empty_when_upgrade_advice_is_none(tmp_path):
    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = None
    run_id = _make_run_id()

    patches = engine._build_minimal_execution_probe_patch(run_id)

    assert patches == []


def test_probe_does_not_target_engine_py(tmp_path):
    """Probe must never target engine.py even if it is among required targets."""
    target_dir = tmp_path / "src" / "the_daddy"
    target_dir.mkdir(parents=True)
    (target_dir / "engine.py").write_text("# engine\n", encoding="utf-8")

    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": ["src/the_daddy/engine.py"], "repair_mode": True}
    run_id = _make_run_id()

    patches = engine._build_minimal_execution_probe_patch(run_id)

    assert patches == []


def test_probe_wired_into_repair_mode_fallback_block(tmp_path, monkeypatch):
    """Probe targets cli.py (not engine.py or README.md) in the fallback block."""
    target_dir = tmp_path / "src" / "the_daddy"
    target_dir.mkdir(parents=True)
    (target_dir / "cli.py").write_text("# cli\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Repo\n", encoding="utf-8")

    monkeypatch.setattr(os.path, "exists", lambda p: p == CLI_PROBE_TARGET)

    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.repair_mode_active = True
    engine.upgrade_advice = {"target_files": [CLI_PROBE_TARGET], "repair_mode": True}

    run_id = _make_run_id()
    patches = engine._build_minimal_execution_probe_patch(run_id)

    assert len(patches) == 1
    assert patches[0].path == CLI_PROBE_TARGET
    assert patches[0].path != "README.md"
    assert patches[0].path != "src/the_daddy/engine.py"

