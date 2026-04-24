from __future__ import annotations

import os

from the_daddy.engine import CLI_PROBE_TARGET, DaddyEngine, make_run_id
from the_daddy.models import PatchAction


def _make_settings_with_root(tmp_path):
    from the_daddy.config import Settings

    s = Settings()
    s.target_root = tmp_path
    s.github_repo = ""
    s.github_token = ""
    return s


def test_masked_advice_target_generates_real_patch_path(tmp_path, monkeypatch):
    """Masked advice target src/the_***/cli.py must generate patch path src/the_daddy/cli.py."""
    monkeypatch.setattr(os.path, "exists", lambda p: p == CLI_PROBE_TARGET)

    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": ["src/the_***/cli.py"], "repair_mode": True}
    run_id = make_run_id()

    patches = engine._build_minimal_execution_probe_patch(run_id)

    assert len(patches) == 1
    p = patches[0]
    assert isinstance(p, PatchAction)
    assert p.path == CLI_PROBE_TARGET


def test_generated_patch_path_never_contains_masked_segment(tmp_path, monkeypatch):
    """Generated patch path must never contain the string 'the_***'."""
    monkeypatch.setattr(os.path, "exists", lambda p: p == CLI_PROBE_TARGET)

    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": ["src/the_***/cli.py"], "repair_mode": True}
    run_id = make_run_id()

    patches = engine._build_minimal_execution_probe_patch(run_id)

    for patch in patches:
        assert "the_***" not in (patch.path or "")


def test_engine_only_target_returns_empty(tmp_path):
    """Engine-only target (engine.py, not cli.py) still returns []."""
    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": ["src/the_daddy/engine.py"], "repair_mode": True}
    run_id = make_run_id()

    patches = engine._build_minimal_execution_probe_patch(run_id)

    assert patches == []
