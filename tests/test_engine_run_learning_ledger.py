from __future__ import annotations

import json
from pathlib import Path

import the_daddy.engine as engine_module
from the_daddy.engine import DaddyEngine
from the_daddy.models import ArchitectureReview, PatchAction, RunRecord, SelfEvolutionAction


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
    s.local_state_dir = tmp_path / "local_state"
    s.memory_file_name = "test-memory.json"
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
    raised = {"done": False}

    def _flaky_save(payload):
        ledger = payload.get("run_learning_ledger", []) if isinstance(payload, dict) else []
        if not raised["done"] and isinstance(ledger, list) and ledger:
            raised["done"] = True
            raise RuntimeError("OPENAI_API_KEY=sk-very-secret-value")
        return original_save(payload)

    monkeypatch.setattr(engine.memory.store, "save", _flaky_save)
    record = engine.run()
    assert record.success is True
    events = [e for e in record.trace if e.get("event") == "run_learning_ledger_save_failed"]
    assert events
    assert "[REDACTED" in json.dumps(events[-1])


def test_patch_apply_failed_and_failure_pattern_text_are_sanitized(tmp_path: Path, monkeypatch):
    advice_path = tmp_path / "advice.json"
    _write_advice(advice_path, next_step="repair")
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

    runtime_dir = tmp_path / "src" / "the_daddy" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "trace_summary.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "src" / "the_daddy" / "cli.py").write_text("def x():\n    return 1\n", encoding="utf-8")

    engine = DaddyEngine(_settings(tmp_path))
    patch = PatchAction(
        path="src/the_daddy/runtime/trace_summary.py",
        operation="regex_replace",
        pattern=r"\Z",
        replacement="\n# test\n",
        description="force apply fail",
    )
    action = SelfEvolutionAction(title="a", description="d", risk="safe", patches=[patch])
    monkeypatch.setattr(
        engine.reviewer,
        "review",
        lambda **_: ArchitectureReview(
            diagnosis="d",
            system_intent="i",
            strengths=[],
            weaknesses=[],
            recommendations=[],
            backlog_items=[],
            self_evolution_actions=[action],
            build_actions=[],
            architecture_plans=[],
            execution_notes=[],
            risk_level="low",
        ),
    )

    original_apply = engine_module.apply_patch_action

    def _boom_apply(*_args, **_kwargs):
        raise RuntimeError(
            "Authorization: Bearer sk-test-secret OPENAI_API_KEY=sk-test-secret "
            "GITHUB_TOKEN=ghp_testsecret password=supersecret"
        )

    monkeypatch.setattr(engine_module, "apply_patch_action", _boom_apply)
    try:
        record = engine.run()
    finally:
        monkeypatch.setattr(engine_module, "apply_patch_action", original_apply)

    failed = [e for e in record.trace if e.get("event") == "patch_apply_failed"]
    assert failed
    failed_blob = json.dumps(failed[-1])
    for secret in [
        "sk-test-secret",
        "ghp_testsecret",
        "supersecret",
        "Authorization: Bearer",
    ]:
        assert secret not in failed_blob
    assert "Authorization: [REDACTED_AUTH_HEADER]" in failed_blob
    assert "OPENAI_API_KEY=[REDACTED_SECRET]" in failed_blob
    assert "GITHUB_TOKEN=[REDACTED_TOKEN]" in failed_blob
    assert "password=[REDACTED_SECRET]" in failed_blob

    patterns = list(engine.memory.state.failure_patterns.values())
    assert patterns
    summary_blob = json.dumps(patterns[-1].model_dump(mode="json"))
    for secret in [
        "sk-test-secret",
        "ghp_testsecret",
        "supersecret",
        "Authorization: Bearer",
    ]:
        assert secret not in summary_blob
    assert "Authorization: [REDACTED_AUTH_HEADER]" in summary_blob
    assert "OPENAI_API_KEY=[REDACTED_SECRET]" in summary_blob
    assert "GITHUB_TOKEN=[REDACTED_TOKEN]" in summary_blob
    assert "password=[REDACTED_SECRET]" in summary_blob


def test_pr_delivery_failed_error_is_sanitized(tmp_path: Path, monkeypatch):
    advice_path = tmp_path / "advice.json"
    _write_advice(advice_path, next_step="no_action")
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

    (tmp_path / "src" / "the_daddy").mkdir(parents=True)
    (tmp_path / "src" / "the_daddy" / "cli.py").write_text("def x():\n    return 1\n", encoding="utf-8")

    engine = DaddyEngine(_settings(tmp_path))
    monkeypatch.setattr(engine, "choose_mode", lambda _review: "architecture")
    monkeypatch.setattr(engine.reviewer, "review", lambda **_: _review())
    monkeypatch.setattr(engine, "_can_use_pr_lane", lambda _record: (True, ""))

    def _raise_pr(*_args, **_kwargs):
        raise RuntimeError(
            "Authorization: Bearer sk-test-secret OPENAI_API_KEY=sk-test-secret "
            "GITHUB_TOKEN=ghp_testsecret password=supersecret"
        )

    monkeypatch.setattr(engine, "_deliver_patch_via_pr", _raise_pr)
    record = engine.run()
    events = [e for e in record.trace if e.get("event") == "pr_delivery_failed"]
    assert events
    blob = json.dumps(events[-1])
    for secret in [
        "sk-test-secret",
        "ghp_testsecret",
        "supersecret",
        "Authorization: Bearer",
    ]:
        assert secret not in blob
    assert "Authorization: [REDACTED_AUTH_HEADER]" in blob
    assert "OPENAI_API_KEY=[REDACTED_SECRET]" in blob
    assert "GITHUB_TOKEN=[REDACTED_TOKEN]" in blob
    assert "password=[REDACTED_SECRET]" in blob


def test_branch_prepare_failed_error_is_sanitized(tmp_path: Path, monkeypatch):
    advice_path = tmp_path / "advice.json"
    _write_advice(advice_path, next_step="repair")
    monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

    runtime_dir = tmp_path / "src" / "the_daddy" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "trace_summary.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "src" / "the_daddy" / "cli.py").write_text("def x():\n    return 1\n", encoding="utf-8")

    engine = DaddyEngine(_settings(tmp_path))
    engine.settings.github_token = "x"
    engine.settings.github_repo = "o/r"
    monkeypatch.setattr(engine, "_is_git_repo", lambda: True)

    patch = PatchAction(
        path="src/the_daddy/runtime/trace_summary.py",
        operation="regex_replace",
        pattern=r"\Z",
        replacement="\n# test\n",
        description="trigger branch prepare",
    )
    action = SelfEvolutionAction(title="a", description="d", risk="safe", patches=[patch])
    monkeypatch.setattr(
        engine.reviewer,
        "review",
        lambda **_: ArchitectureReview(
            diagnosis="d",
            system_intent="i",
            strengths=[],
            weaknesses=[],
            recommendations=[],
            backlog_items=[],
            self_evolution_actions=[action],
            build_actions=[],
            architecture_plans=[],
            execution_notes=[],
            risk_level="low",
        ),
    )
    monkeypatch.setattr(
        engine.git_tools,
        "prepare_branch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError(
                "Authorization: Bearer sk-test-secret OPENAI_API_KEY=sk-test-secret "
                "GITHUB_TOKEN=ghp_testsecret password=supersecret"
            )
        ),
    )
    record = engine.run()
    events = [e for e in record.trace if e.get("event") == "branch_prepare_failed"]
    assert events
    blob = json.dumps(events[-1])
    for fragment in [
        "sk-test-secret",
        "ghp_testsecret",
        "supersecret",
        "Authorization: Bearer sk-test-secret",
        "OPENAI_API_KEY=sk-test-secret",
        "GITHUB_TOKEN=ghp_testsecret",
        "password=supersecret",
    ]:
        assert fragment not in blob
    assert "Authorization: [REDACTED_AUTH_HEADER]" in blob
    assert "OPENAI_API_KEY=[REDACTED_SECRET]" in blob
    assert "GITHUB_TOKEN=[REDACTED_TOKEN]" in blob
    assert "password=[REDACTED_SECRET]" in blob


def test_doctor_takeover_trace_fields_are_sanitized(tmp_path: Path, monkeypatch):
    engine = DaddyEngine(_settings(tmp_path))
    engine.repair_mode_active = True
    engine.upgrade_advice = {"target_files": ["src/the_daddy/cli.py"], "repair_mode": True}
    monkeypatch.setattr(engine, "_recent_same_blocker_count", lambda _blocker: 5)
    monkeypatch.setattr(engine, "_stuck_same_reason_limit", lambda: 2)
    monkeypatch.setattr(
        engine,
        "_target_file_snapshots",
        lambda: [{"path": "src/the_daddy/cli.py", "content": "def x():\n    return 1\n"}],
    )
    engine.doctor_executor.plan_patches = lambda **_kwargs: {
        "diagnosis": "Authorization: Bearer sk-test-secret",
        "root_cause": "OPENAI_API_KEY=sk-test-secret GITHUB_TOKEN=ghp_testsecret password=supersecret",
        "changes": [],
    }
    record = RunRecord(run_id="r-doc", command="pytest -q")
    _ = engine._doctor_takeover_patches(record)
    events = [e for e in record.trace if e.get("event") == "doctor_agent_takeover"]
    assert events
    blob = json.dumps(events[-1])
    for fragment in [
        "sk-test-secret",
        "ghp_testsecret",
        "supersecret",
        "Authorization: Bearer sk-test-secret",
        "OPENAI_API_KEY=sk-test-secret",
        "GITHUB_TOKEN=ghp_testsecret",
        "password=supersecret",
    ]:
        assert fragment not in blob
    assert "Authorization: [REDACTED_AUTH_HEADER]" in blob
    assert "OPENAI_API_KEY=[REDACTED_SECRET]" in blob
    assert "GITHUB_TOKEN=[REDACTED_TOKEN]" in blob
    assert "password=[REDACTED_SECRET]" in blob
