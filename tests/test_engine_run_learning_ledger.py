from __future__ import annotations

import json
from pathlib import Path

from the_daddy.engine import DaddyEngine
from the_daddy.models import ArchitectureReview


def _write_advice(path: Path, *, next_step: str = "repair") -> None:
    payload = {
        "allow_proceed": True,
        "summary": "ok",
        "repo_state": "clean",
        "problem_type": "healthy_meaningful_progress",
        "recommended_next_step": next_step,
        "target_files": ["src/the_daddy/cli.py"] if next_step != "no_action" else [],
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


def _review() -> ArchitectureReview:
    return ArchitectureReview(
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
    )


def test_ledger_save_failure_is_traced_without_masking_run_result(tmp_path: Path, monkeypatch):
    advice_path = tmp_path / "advice.json"
    _write_advice(advice_path, next_step="no_action")
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

    (tmp_path / "src" / "the_daddy").mkdir(parents=True)
    (tmp_path / "src" / "the_daddy" / "cli.py").write_text("def x():\n    return 1\n", encoding="utf-8")

    engine = DaddyEngine(_settings(tmp_path))
    monkeypatch.setattr(engine, "choose_mode", lambda _review: "architecture")
    monkeypatch.setattr(engine.reviewer, "review", lambda **_: _review())

    def _boom(_entry):
        raise RuntimeError("save failed Authorization: Bearer sk-SECRETSECRETSECRETSECRET")

    monkeypatch.setattr(engine.memory, "add_run_learning_entry", _boom)
    record = engine.run()

    assert record.success is True
    failure_events = [e for e in record.trace if e.get("event") == "run_learning_ledger_save_failed"]
    assert failure_events
    serialized = json.dumps(failure_events[-1])
    assert "sk-SECRETSECRETSECRETSECRET" not in serialized
    assert "Authorization: Bearer" not in serialized
    assert "[REDACTED" in serialized
    assert not any(e.get("event") == "run_learning_ledger_saved" for e in record.trace)


def test_store_save_failure_during_ledger_write_does_not_mask_run(tmp_path: Path, monkeypatch):
    advice_path = tmp_path / "advice.json"
    _write_advice(advice_path, next_step="no_action")
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

    (tmp_path / "src" / "the_daddy").mkdir(parents=True)
    (tmp_path / "src" / "the_daddy" / "cli.py").write_text("def x():\n    return 1\n", encoding="utf-8")

    engine = DaddyEngine(_settings(tmp_path))
    monkeypatch.setattr(engine, "choose_mode", lambda _review: "architecture")
    monkeypatch.setattr(engine.reviewer, "review", lambda **_: _review())

    original_save = engine.memory.store.save
    calls = {"n": 0}

    def _flaky_save(payload):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("OPENAI_API_KEY=sk-very-secret-value")
        return original_save(payload)

    monkeypatch.setattr(engine.memory.store, "save", _flaky_save)
    record = engine.run()
    assert record.success is True
    events = [e for e in record.trace if e.get("event") == "run_learning_ledger_save_failed"]
    assert events
    assert "[REDACTED" in json.dumps(events[-1])
