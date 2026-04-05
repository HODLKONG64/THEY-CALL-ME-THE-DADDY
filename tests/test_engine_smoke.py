from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from the_daddy.config import Settings
from the_daddy.engine import DaddyEngine


def _write_advice(path: Path, *, allow_proceed: bool = True) -> Path:
    payload = {
        "allow_proceed": allow_proceed,
        "summary": "approved" if allow_proceed else "rejected",
        "repo_state": "test_repo_state",
        "problem_type": "healthy_meaningful_progress" if allow_proceed else "healthy_safe_loop",
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
