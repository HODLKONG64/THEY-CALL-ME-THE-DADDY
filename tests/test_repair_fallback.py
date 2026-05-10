from __future__ import annotations

from the_daddy.engine import DaddyEngine, make_run_id
from the_daddy.models import RunRecord


def _make_settings_with_root(tmp_path):
    from the_daddy.config import Settings

    s = Settings()
    s.target_root = tmp_path
    s.github_repo = ""
    s.github_token = ""
    return s


def _make_record() -> RunRecord:
    return RunRecord(run_id=make_run_id(), command="pytest -q")


def test_repair_fallback_forced_readme_disabled(tmp_path):
    (tmp_path / "README.md").write_text("# Repo\n\ninitial\n", encoding="utf-8")
    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": ["src/the_daddy/engine.py"], "repair_mode": True}
    record = _make_record()

    patches = engine._build_forced_target_patches(record)
    assert patches == []


def test_forced_fallback_disabled_emits_explicit_skip_reason(tmp_path):
    (tmp_path / "README.md").write_text("hello\n")
    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": ["src/the_daddy/engine.py"], "repair_mode": True}
    record = _make_record()
    patches = engine._build_forced_target_patches(record)
    assert patches == []
    evt = next((e for e in record.trace if e.get("event") == "forced_target_patch_generation_skipped"), None)
    assert evt is not None
    assert "forced README fallback disabled" in str(evt.get("reason", ""))


def test_fallback_patch_is_not_generated(tmp_path):
    (tmp_path / "README.md").write_text("hello\n")
    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": ["src/the_daddy/engine.py"], "repair_mode": True}
    record = _make_record()
    patches = engine._build_forced_target_patches(record)
    assert patches == []


def test_no_readme_no_fallback(tmp_path):
    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": ["src/the_daddy/engine.py"], "repair_mode": True}
    record = _make_record()
    patches = engine._build_forced_target_patches(record)
    assert patches == []
    assert any(e.get("event") == "forced_target_patch_generation_skipped" for e in record.trace)
