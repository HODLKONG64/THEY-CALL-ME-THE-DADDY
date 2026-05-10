from __future__ import annotations

import json
from pathlib import Path

from the_daddy.core import request_upgrade_advice as advice_module


def test_build_learning_summary_reads_recent_ledger(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DADDY_LOCAL_STATE_DIR", "doctor_local")
    monkeypatch.setenv("DADDY_MEMORY_FILE", "sam-memory.json")
    memory_dir = tmp_path / "doctor_local"
    memory_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "3.0",
        "run_learning_ledger": [
            {"run_id": "r1", "outcome": "blocked_fake_noop", "subsystem": "engine", "blocked_reason": "no patch"},
            {"run_id": "r2", "outcome": "success_with_patch", "subsystem": "engine", "what_worked": ["applied_patches=1"]},
        ],
    }
    (memory_dir / "sam-memory.json").write_text(json.dumps(payload), encoding="utf-8")

    summary = advice_module.build_learning_summary(tmp_path)
    assert summary["recent_outcomes"] == ["blocked_fake_noop", "success_with_patch"]
    assert summary["recurring_blockers"][0]["blocked_reason"] == "no patch"


def test_request_upgrade_advice_includes_learning_summary(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DADDY_LOCAL_STATE_DIR", "doctor_local")
    monkeypatch.setenv("DADDY_MEMORY_FILE", "sam-memory.json")
    memory_dir = tmp_path / "doctor_local"
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "sam-memory.json").write_text(
        json.dumps({"schema_version": "3.0", "run_learning_ledger": [{"run_id": "r1", "outcome": "blocked_fake_noop"}]}),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "output_text": json.dumps(
                    {
                        "allow_proceed": True,
                        "summary": "ok",
                        "repo_state": "clean",
                        "problem_type": "healthy_meaningful_progress",
                        "recommended_next_step": "repair",
                        "target_files": ["src/the_daddy/cli.py"],
                        "forbidden_repeat_patterns": [],
                        "required_constraints": [],
                        "tests_to_run": ["pytest -q"],
                        "generated_at": "2099-01-01T00:00:00+00:00",
                    }
                )
            }

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, _url: str, *, headers=None, json=None):
            captured["payload"] = json
            return _FakeResponse()

    monkeypatch.setattr(advice_module.httpx, "Client", _FakeClient)
    advice_module.request_upgrade_advice(repo_root=tmp_path, model="gpt-5.4")

    payload = captured["payload"]
    assert isinstance(payload, dict)
    content_text = payload["input"][1]["content"][0]["text"]  # type: ignore[index]
    parsed = json.loads(content_text)
    assert "run_learning_summary" in parsed
    assert parsed["run_learning_summary"]["recent_outcomes"] == ["blocked_fake_noop"]
