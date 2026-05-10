from __future__ import annotations

import json
from pathlib import Path

from the_daddy.engine import DaddyEngine
from the_daddy.models import ArchitectureReview


def _settings(tmp_path: Path):
    from the_daddy.config import Settings

    s = Settings()
    s.target_root = tmp_path
    s.command = "python -c \"print('ok')\""
    s.github_repo = ""
    s.github_token = ""
    return s


def _write_repair_advice(path: Path) -> None:
    payload = {
        "allow_proceed": False,
        "summary": "safe loop",
        "repo_state": "clean",
        "problem_type": "healthy_safe_loop",
        "recommended_next_step": "repair",
        "target_files": ["src/the_daddy/engine.py"],
        "forbidden_repeat_patterns": [],
        "required_constraints": [],
        "tests_to_run": ["pytest -q"],
        "generated_at": "2099-01-01T00:00:00+00:00",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_required_execution_target_repair_skips_helper_lane_and_leaves_no_mutation(tmp_path, monkeypatch):
    advice = tmp_path / "advice.json"
    _write_repair_advice(advice)
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice))

    helper_path = tmp_path / "src" / "the_daddy" / "runtime" / "trace_summary.py"
    helper_path.parent.mkdir(parents=True)
    original_helper = "def base():\n    return {}\n"
    helper_path.write_text(original_helper, encoding="utf-8")

    engine_target = tmp_path / "src" / "the_daddy" / "engine.py"
    engine_target.parent.mkdir(parents=True, exist_ok=True)
    engine_target.write_text("def sentinel():\n    return 1\n", encoding="utf-8")

    engine = DaddyEngine(_settings(tmp_path))
    monkeypatch.setattr(engine.reviewer, "review", lambda **_: ArchitectureReview(
        diagnosis="d",
        system_intent="i",
        strengths=[],
        weaknesses=[],
        recommendations=[],
        backlog_items=[],
        self_evolution_actions=[],
        build_actions=[],
        architecture_plans=[],
        execution_notes=[],
        risk_level="low",
    ))

    record = engine.run()

    events = [e.get("event") for e in record.trace]
    assert "helper_lane_skipped_for_execution_target_repair" in events
    assert "safe_helper_lane_patch_generated" not in events
    assert helper_path.read_text(encoding="utf-8") == original_helper
    assert record.success is False
    assert "Repair mode pending required engine/cli upgrade" in record.summary
    assert any(e.get("event") == "repair_mode_completion_blocked" for e in record.trace)

