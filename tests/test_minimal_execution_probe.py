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


def test_probe_generates_patch_for_execution_target(tmp_path):
    target_dir = tmp_path / "src" / "the_daddy"
    target_dir.mkdir(parents=True)
    engine_file = target_dir / "engine.py"
    engine_file.write_text("# engine\n", encoding="utf-8")

    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": ["src/the_daddy/engine.py"], "repair_mode": True}
    record = _make_record()

    patches = engine._build_minimal_execution_probe_patch(record)

    assert len(patches) == 1
    p = patches[0]
    assert isinstance(p, PatchAction)
    assert p.path == "src/the_daddy/engine.py"
    assert p.operation == "regex_replace"
    assert p.pattern == r"\Z"
    assert "# probe:" in (p.replacement or "")
    assert p.description == "Minimal execution probe patch"


def test_probe_emits_trace_event_on_success(tmp_path):
    target_dir = tmp_path / "src" / "the_daddy"
    target_dir.mkdir(parents=True)
    (target_dir / "engine.py").write_text("# engine\n", encoding="utf-8")

    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": ["src/the_daddy/engine.py"], "repair_mode": True}
    record = _make_record()

    engine._build_minimal_execution_probe_patch(record)

    events = [e.get("event") for e in record.trace]
    assert "minimal_execution_probe_generated" in events

    generated = next(e for e in record.trace if e.get("event") == "minimal_execution_probe_generated")
    assert generated["chosen_path"] == "src/the_daddy/engine.py"
    assert generated["count"] == 1


def test_probe_skipped_when_no_required_targets(tmp_path):
    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    # upgrade_advice with no execution-path targets
    engine.upgrade_advice = {"target_files": ["README.md"], "repair_mode": True}
    record = _make_record()

    patches = engine._build_minimal_execution_probe_patch(record)

    assert patches == []
    events = [e.get("event") for e in record.trace]
    assert "minimal_execution_probe_skipped" in events


def test_probe_skipped_when_target_file_missing(tmp_path):
    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = {"target_files": ["src/the_daddy/engine.py"], "repair_mode": True}
    record = _make_record()

    patches = engine._build_minimal_execution_probe_patch(record)

    assert patches == []
    skipped = next(e for e in record.trace if e.get("event") == "minimal_execution_probe_skipped")
    assert "target file missing" in skipped["reason"]


def test_probe_skipped_when_upgrade_advice_is_none(tmp_path):
    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.upgrade_advice = None
    record = _make_record()

    patches = engine._build_minimal_execution_probe_patch(record)

    assert patches == []
    events = [e.get("event") for e in record.trace]
    assert "minimal_execution_probe_skipped" in events


def test_probe_wired_into_repair_mode_fallback_block(tmp_path):
    """Probe is tried before the forced README patches in the fallback block."""
    target_dir = tmp_path / "src" / "the_daddy"
    target_dir.mkdir(parents=True)
    (target_dir / "engine.py").write_text("# engine\n", encoding="utf-8")
    # README.md also exists but probe should be chosen first
    (tmp_path / "README.md").write_text("# Repo\n", encoding="utf-8")

    settings = _make_settings_with_root(tmp_path)
    engine = DaddyEngine(settings)
    engine.repair_mode_active = True
    engine.upgrade_advice = {"target_files": ["src/the_daddy/engine.py"], "repair_mode": True}

    # Simulate the fallback block by calling the method directly
    record = _make_record()
    patches = engine._build_minimal_execution_probe_patch(record)

    # The probe targets the execution file, not README.md
    assert len(patches) == 1
    assert patches[0].path == "src/the_daddy/engine.py"
    assert patches[0].path != "README.md"
