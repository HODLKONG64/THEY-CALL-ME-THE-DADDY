from __future__ import annotations

import json
from pathlib import Path

from the_daddy.engine import DaddyEngine
from the_daddy.models import ArchitectureReview


def _write_advice(path: Path, *, allow_proceed: bool, problem_type: str) -> None:
    payload = {
        "allow_proceed": allow_proceed,
        "summary": "ok",
        "repo_state": "clean",
        "problem_type": problem_type,
        "recommended_next_step": "repair",
        "target_files": ["src/the_daddy/cli.py"],
        "forbidden_repeat_patterns": [],
        "required_constraints": [],
        "tests_to_run": ["pytest -q"],
        "generated_at": "2099-01-01T00:00:00+00:00",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _settings(tmp_path: Path):
    from the_daddy.config import Settings

    s = Settings()
    s.target_root = tmp_path
    s.command = "python -c \"print('ok')\""
    s.github_token = ""
    s.github_repo = ""
    return s


def test_run_blocks_success_when_no_patch_applied(tmp_path, monkeypatch):
    advice_path = tmp_path / "advice.json"
    _write_advice(advice_path, allow_proceed=True, problem_type="healthy_meaningful_progress")
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

    (tmp_path / "src" / "the_daddy").mkdir(parents=True)
    (tmp_path / "src" / "the_daddy" / "cli.py").write_text("def x():\n    return 1\n", encoding="utf-8")

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
    assert record.success is False
    assert "No patch applied" in record.summary
    assert any(e.get("event") == "no_patch_blocker_recorded" for e in record.trace)

