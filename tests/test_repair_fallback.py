from __future__ import annotations

from the_daddy.engine import DaddyEngine, make_run_id
from the_daddy.models import PatchAction, RunRecord


def _make_settings_with_root(tmp_path):
    from the_daddy.config import Settings

    s = Settings()
    s.target_root = tmp_path
    s.github_repo = ""
    s.github_token = ""
    return s


def _make_record() -> RunRecord:
    return RunRecord(run_id=make_run_id(), command="pytest -q")


def test_repair_fallback_creates_readme_patch(tmp_path):
    (tmp_path / "README.md").write_text("# Repo\n\ninitial\n", encoding="utf-8")
    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": ["src/the_daddy/engine.py"], "repair_mode": True}
    record = _make_record()

    patches = engine._build_forced_target_patches(record)
    assert len(patches) == 1
    p = patches[0]
    assert isinstance(p, PatchAction)
    assert p.path == "README.md"
    assert p.operation == "regex_replace"
    assert p.pattern == r"\Z"
    assert "<!-- forced-repair-heartbeat:" in (p.replacement or "")


def test_fallback_patch_does_not_target_engine(tmp_path):
    (tmp_path / "README.md").write_text("hello\n")
    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": ["src/the_daddy/engine.py"], "repair_mode": True}
    record = _make_record()
    patches = engine._build_forced_target_patches(record)
    assert all(p.path != "src/the_daddy/engine.py" for p in patches)


def test_fallback_patch_is_considered_merge_safe(tmp_path):
    (tmp_path / "README.md").write_text("hello\n")
    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": ["src/the_daddy/engine.py"], "repair_mode": True}
    record = _make_record()
    patches = engine._build_forced_target_patches(record)
    assert len(patches) == 1
    p = patches[0]
    assert engine.merge_judge.is_safe_file(p.path)


def test_no_readme_no_fallback(tmp_path):
    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": ["src/the_daddy/engine.py"], "repair_mode": True}
    record = _make_record()
    patches = engine._build_forced_target_patches(record)
    assert patches == []
    assert any(e.get("event") == "forced_target_patch_generation_skipped" for e in record.trace)
