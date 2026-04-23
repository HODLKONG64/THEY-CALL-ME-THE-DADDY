from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from the_daddy.config import Settings
from the_daddy.engine import DaddyEngine
from the_daddy.models import RunRecord


def _write_advice(path: Path, *, allow_proceed: bool = True, problem_type: str | None = None) -> Path:
    payload = {
        "allow_proceed": allow_proceed,
        "summary": "approved" if allow_proceed else "rejected",
        "repo_state": "test_repo_state",
        "problem_type": problem_type or ("healthy_meaningful_progress" if allow_proceed else "healthy_safe_loop"),
        "recommended_next_step": "run bounded upgrade",
        "target_files": ["src/the_daddy/engine.py"],
        "forbidden_repeat_patterns": [],
        "required_constraints": ["small changes only"],
        "tests_to_run": ["pytest -q"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_engine_runs_with_upgrade_gate_bypassed(tmp_path):
    settings = Settings(
        target_root=tmp_path,
        command="python -c \"print('ok')\"",
        enable_self_evolution=False,
        enable_architecture_lane=False,
    )
    engine = DaddyEngine(settings)
    result = engine.run()
    assert result is not None


def test_engine_runs_with_approved_upgrade_advice(tmp_path, monkeypatch):
    advice_path = _write_advice(tmp_path / "upgrade_advice.json", allow_proceed=True)
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

    settings = Settings(
        target_root=tmp_path,
        command="python -c \"print('ok')\"",
    )
    engine = DaddyEngine(settings)
    result = engine.run()
    assert result is not None


def test_engine_runs_in_repair_mode_for_safe_loop(tmp_path, monkeypatch):
    advice_path = _write_advice(
        tmp_path / "repair_mode.json",
        allow_proceed=False,
        problem_type="healthy_safe_loop",
    )
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

    settings = Settings(
        target_root=tmp_path,
        command="python -c \"print('ok')\"",
    )
    engine = DaddyEngine(settings)
    result = engine.run()
    assert result is not None
    assert engine.repair_mode_active is True


def _write_repair_advice(path: Path, target_files: list[str]) -> Path:
    payload = {
        "allow_proceed": False,
        "summary": "rejected",
        "repo_state": "repair_needed",
        "problem_type": "healthy_safe_loop",
        "recommended_next_step": "fix execution target",
        "repair_mode": True,
        "target_files": target_files,
        "forbidden_repeat_patterns": [],
        "required_constraints": [],
        "tests_to_run": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_build_forced_target_patches_returns_one_patch_when_engine_exists(tmp_path, monkeypatch):
    engine_stub = tmp_path / "src" / "the_daddy" / "engine.py"
    engine_stub.parent.mkdir(parents=True)
    engine_stub.write_text("# stub engine\n", encoding="utf-8")

    advice_path = _write_repair_advice(
        tmp_path / "repair_advice.json",
        target_files=["src/the_daddy/engine.py"],
    )
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

    settings = Settings(target_root=tmp_path, command="echo ok")
    engine = DaddyEngine(settings)
    record = RunRecord(run_id="test-forced", command="echo ok")
    engine._enforce_upgrade_gate(record)

    assert engine.repair_mode_active is True
    assert engine._required_execution_targets() == ["src/the_daddy/engine.py"]

    patches = engine._build_forced_target_patches(record)
    assert len(patches) == 1
    patch = patches[0]
    assert patch.path == "src/the_daddy/engine.py"
    assert patch.operation == "regex_replace"
    assert "DADDY_REPAIR_FALLBACK_MARKER" in patch.replacement
    forced_events = [e for e in record.trace if e.get("event") == "forced_target_patch_generated"]
    assert len(forced_events) == 1
    assert forced_events[0]["count"] == 1


def test_build_forced_target_patches_updates_existing_marker(tmp_path, monkeypatch):
    engine_stub = tmp_path / "src" / "the_daddy" / "engine.py"
    engine_stub.parent.mkdir(parents=True)
    engine_stub.write_text(
        '# stub\nDADDY_REPAIR_FALLBACK_MARKER = "20240101T000000Z"\n',
        encoding="utf-8",
    )

    advice_path = _write_repair_advice(
        tmp_path / "repair_advice.json",
        target_files=["src/the_daddy/engine.py"],
    )
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

    settings = Settings(target_root=tmp_path, command="echo ok")
    engine = DaddyEngine(settings)
    record = RunRecord(run_id="test-update-marker", command="echo ok")
    engine._enforce_upgrade_gate(record)

    patches = engine._build_forced_target_patches(record)
    assert len(patches) == 1
    patch = patches[0]
    assert patch.operation == "regex_replace"
    assert "DADDY_REPAIR_FALLBACK_MARKER" in patch.pattern


def test_build_forced_target_patches_returns_empty_when_no_required_targets(tmp_path, monkeypatch):
    advice_path = _write_advice(
        tmp_path / "repair_mode.json",
        allow_proceed=False,
        problem_type="healthy_safe_loop",
    )
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

    settings = Settings(target_root=tmp_path, command="echo ok")
    engine = DaddyEngine(settings)
    record = RunRecord(run_id="test-no-targets", command="echo ok")
    engine._enforce_upgrade_gate(record)

    engine.upgrade_advice["target_files"] = []
    patches = engine._build_forced_target_patches(record)
    assert patches == []


def test_build_forced_target_patches_returns_empty_when_file_missing(tmp_path, monkeypatch):
    advice_path = _write_repair_advice(
        tmp_path / "repair_advice.json",
        target_files=["src/the_daddy/engine.py"],
    )
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

    settings = Settings(target_root=tmp_path, command="echo ok")
    engine = DaddyEngine(settings)
    record = RunRecord(run_id="test-no-file", command="echo ok")
    engine._enforce_upgrade_gate(record)

    patches = engine._build_forced_target_patches(record)
    assert patches == []
    skipped_events = [e for e in record.trace if e.get("event") == "forced_target_patch_generation_skipped"]
    assert len(skipped_events) == 1


def test_repair_mode_deadlock_path_emits_no_patches_remaining_event(tmp_path, monkeypatch):
    engine_stub = tmp_path / "src" / "the_daddy" / "engine.py"
    engine_stub.parent.mkdir(parents=True)
    engine_stub.write_text("# stub engine\n", encoding="utf-8")

    advice_path = _write_repair_advice(
        tmp_path / "repair_advice.json",
        target_files=["src/the_daddy/engine.py"],
    )
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

    settings = Settings(
        target_root=tmp_path,
        command="python -c \"print('ok')\"",
        enable_self_evolution=False,
    )
    engine = DaddyEngine(settings)
    result = engine.run()
    assert result is not None

    events = [e.get("event") for e in result.trace]
    assert "repair_mode_no_patches_remaining" in events
    assert "forced_target_patch_generated" in events
