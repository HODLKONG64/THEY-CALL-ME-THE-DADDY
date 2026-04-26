"""Tests for the safe helper-lane fallback patch builder.

Covers the required behavior:
- healthy_safe_loop with no candidate patches generates a helper-lane patch
- helper-lane fallback never targets README.md
- helper-lane fallback never targets engine.py or cli.py
- if helper-lane patch unavailable, clean no-op still works
- attempted helper-lane patch with failing verification still fails CI
- generated trace includes safe_helper_lane_patch_generated
- old no-op behavior still allowed when no helper-lane patch available
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from the_daddy.engine import (
    SAFE_HELPER_LANE_TARGETS,
    DaddyEngine,
    make_run_id,
)
from the_daddy.models import PatchAction, RunRecord
from the_daddy.policy import classify_patch_risk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(tmp_path: Path, *, command: str = "python -c \"print('ok')\""):
    from the_daddy.config import Settings

    s = Settings()
    s.target_root = tmp_path
    s.github_repo = ""
    s.github_token = ""
    s.command = command
    return s


def _make_engine(tmp_path: Path, *, command: str = "python -c \"print('ok')\"") -> DaddyEngine:
    return DaddyEngine(_make_settings(tmp_path, command=command))


def _make_record() -> RunRecord:
    return RunRecord(run_id=make_run_id(), command="pytest -q")


def _set_healthy_safe_loop(engine: DaddyEngine) -> None:
    """Configure engine as if upgrade gate returned healthy_safe_loop."""
    engine.upgrade_advice = {
        "target_files": ["src/the_daddy/engine.py"],
        "repair_mode": True,
        "problem_type": "healthy_safe_loop",
        "allow_proceed": False,
    }
    engine.repair_mode_active = True


def _write_trace_summary(tmp_path: Path) -> Path:
    """Write a minimal trace_summary.py to tmp_path for testing."""
    dest = tmp_path / "src" / "the_daddy" / "runtime"
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "trace_summary.py"
    target.write_text(
        "from __future__ import annotations\n\nfrom typing import Any\n\n"
        "def summarize_trace(trace):\n    return {}\n",
        encoding="utf-8",
    )
    return target


# ---------------------------------------------------------------------------
# Core helper-lane builder tests
# ---------------------------------------------------------------------------

class TestBuildSafeHelperLanePatch:
    def test_generates_patch_for_healthy_safe_loop(self, tmp_path):
        _write_trace_summary(tmp_path)
        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert len(patches) == 1
        p = patches[0]
        assert isinstance(p, PatchAction)
        assert "trace_summary" in p.path

    def test_generates_patch_for_repair_mode_active(self, tmp_path):
        _write_trace_summary(tmp_path)
        engine = _make_engine(tmp_path)
        engine.upgrade_advice = {
            "target_files": ["src/the_daddy/engine.py"],
            "repair_mode": True,
            "problem_type": "other",
        }
        engine.repair_mode_active = True
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert len(patches) == 1

    def test_no_patch_when_not_repair_mode(self, tmp_path):
        _write_trace_summary(tmp_path)
        engine = _make_engine(tmp_path)
        engine.upgrade_advice = {"problem_type": "healthy_meaningful_progress"}
        engine.repair_mode_active = False
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert patches == []

    def test_never_targets_readme(self, tmp_path):
        _write_trace_summary(tmp_path)
        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert all("readme" not in p.path.lower() for p in patches)
        assert all(p.path != "README.md" for p in patches)

    def test_never_targets_engine_py(self, tmp_path):
        _write_trace_summary(tmp_path)
        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert all(p.path != "src/the_daddy/engine.py" for p in patches)

    def test_never_targets_cli_py(self, tmp_path):
        _write_trace_summary(tmp_path)
        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert all(p.path != "src/the_daddy/cli.py" for p in patches)

    def test_trace_event_safe_helper_lane_patch_generated(self, tmp_path):
        _write_trace_summary(tmp_path)
        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        engine._build_safe_helper_lane_patch(record)

        events = [e.get("event") for e in record.trace]
        assert "safe_helper_lane_patch_generated" in events

    def test_trace_event_includes_chosen_path_and_run_id(self, tmp_path):
        _write_trace_summary(tmp_path)
        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        engine._build_safe_helper_lane_patch(record)

        evt = next(
            (e for e in record.trace if e.get("event") == "safe_helper_lane_patch_generated"),
            None,
        )
        assert evt is not None
        assert "chosen_path" in evt
        assert "run_id" in evt
        assert "reason" in evt

    def test_patch_passes_classify_patch_risk(self, tmp_path):
        _write_trace_summary(tmp_path)
        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert len(patches) == 1
        result = classify_patch_risk(patches)
        assert result.passed, f"classify_patch_risk failed: {result.reasons}"

    def test_patch_is_idempotent_when_function_already_exists(self, tmp_path):
        """If summarize_noop_repair_state already exists AND no other targets present,
        no patch is generated."""
        dest = tmp_path / "src" / "the_daddy" / "runtime"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "trace_summary.py").write_text(
            "def summarize_noop_repair_state(run_payload): return {}\n",
            encoding="utf-8",
        )
        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        # trace_summary has the guard, other helpers don't exist in tmp_path → empty
        assert patches == []

    def test_falls_back_to_run_health_when_trace_summary_already_patched(self, tmp_path):
        """When trace_summary already has its function, fallback targets run_health.py."""
        dest = tmp_path / "src" / "the_daddy" / "runtime"
        dest.mkdir(parents=True, exist_ok=True)
        # trace_summary already patched
        (dest / "trace_summary.py").write_text(
            "def summarize_noop_repair_state(run_payload): return {}\n",
            encoding="utf-8",
        )
        # run_health exists but doesn't have the guard symbol
        (dest / "run_health.py").write_text(
            "def summarize_run_health(runs=None): return {}\n",
            encoding="utf-8",
        )

        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert len(patches) == 1
        assert "run_health" in patches[0].path
        assert "summarize_repair_noop_ticks" in patches[0].description

    def test_falls_back_to_error_digest_when_first_two_already_patched(self, tmp_path):
        """When trace_summary and run_health are both patched, error_digest is targeted."""
        dest = tmp_path / "src" / "the_daddy" / "runtime"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "trace_summary.py").write_text(
            "def summarize_noop_repair_state(run_payload): return {}\n",
            encoding="utf-8",
        )
        (dest / "run_health.py").write_text(
            "def summarize_repair_noop_ticks(runs=None): return {}\n",
            encoding="utf-8",
        )
        (dest / "error_digest.py").write_text(
            "def summarize_errors(events=None): return {}\n",
            encoding="utf-8",
        )

        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert len(patches) == 1
        assert "error_digest" in patches[0].path

    def test_patch_unavailable_emits_safe_helper_lane_patch_unavailable(self, tmp_path):
        """When no helper targets exist, emits unavailable event instead."""
        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert patches == []
        events = [e.get("event") for e in record.trace]
        assert "safe_helper_lane_patch_unavailable" in events


# ---------------------------------------------------------------------------
# SAFE_HELPER_LANE_TARGETS constant checks
# ---------------------------------------------------------------------------

class TestSafeHelperLaneTargetsConstant:
    def test_does_not_contain_readme(self):
        for t in SAFE_HELPER_LANE_TARGETS:
            assert "readme" not in t.lower(), f"README found in SAFE_HELPER_LANE_TARGETS: {t}"

    def test_does_not_contain_engine_py(self):
        assert "src/the_daddy/engine.py" not in SAFE_HELPER_LANE_TARGETS

    def test_does_not_contain_cli_py(self):
        assert "src/the_daddy/cli.py" not in SAFE_HELPER_LANE_TARGETS

    def test_all_targets_are_runtime_or_test_or_doc(self):
        for t in SAFE_HELPER_LANE_TARGETS:
            assert (
                t.startswith("src/the_daddy/runtime/")
                or t.startswith("tests/")
                or t.startswith("docs/")
            ), f"Unexpected target outside allowed paths: {t}"


# ---------------------------------------------------------------------------
# Integration: full run() flow with healthy_safe_loop and no candidate patches
# ---------------------------------------------------------------------------

def _write_advice(path: Path, *, allow_proceed: bool = False, problem_type: str = "healthy_safe_loop") -> Path:
    payload = {
        "allow_proceed": allow_proceed,
        "summary": "approved" if allow_proceed else "safe loop",
        "repo_state": "test",
        "problem_type": problem_type,
        "recommended_next_step": "bounded patch",
        "target_files": ["src/the_daddy/engine.py"],
        "forbidden_repeat_patterns": [],
        "required_constraints": [],
        "tests_to_run": ["pytest -q"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestRunFlowHelperLane:
    def test_helper_lane_triggered_when_no_candidate_patches(self, tmp_path, monkeypatch):
        """Full run(): healthy_safe_loop + no reviewer patches → helper-lane patch."""
        _write_trace_summary(tmp_path)
        advice_path = _write_advice(tmp_path / "advice.json")
        monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

        from the_daddy.config import Settings

        settings = Settings(
            target_root=tmp_path,
            command="python -c \"print('ok')\"",
        )
        engine = DaddyEngine(settings)

        # Ensure reviewer produces no patches (no self_evolution_actions)
        from unittest.mock import MagicMock

        mock_review = MagicMock()
        mock_review.self_evolution_actions = []
        mock_review.build_actions = []
        mock_review.architecture_plans = []
        mock_review.execution_notes = []
        mock_review.risk_level = "low"
        mock_review.diagnosis = "test"

        monkeypatch.setattr(engine.reviewer, "review", lambda **_kw: mock_review)
        monkeypatch.setattr(engine.memory, "add_architecture_review", lambda _r: None)
        monkeypatch.setattr(engine.memory, "save", lambda: None)

        record = engine.run()

        events = [e.get("event") for e in record.trace]
        assert "safe_helper_lane_patch_generated" in events, (
            f"Expected safe_helper_lane_patch_generated in trace. Events: {events}"
        )

    def test_helper_lane_not_triggered_when_had_candidate_patches(self, tmp_path, monkeypatch):
        """If reviewer proposed patches (even if filtered), skip helper-lane."""
        _write_trace_summary(tmp_path)
        advice_path = _write_advice(tmp_path / "advice.json")
        monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

        from the_daddy.config import Settings
        from the_daddy.models import SelfEvolutionAction

        settings = Settings(
            target_root=tmp_path,
            command="python -c \"print('ok')\"",
        )
        engine = DaddyEngine(settings)

        # Reviewer produces a patch (pointing somewhere that will be filtered out)
        candidate_patch = PatchAction(
            path="src/the_daddy/engine.py",
            operation="regex_replace",
            pattern=r"DADDY_REPAIR_FALLBACK_MARKER.*",
            replacement="DADDY_REPAIR_FALLBACK_MARKER = \"test\"",
            description="test patch",
        )
        action = SelfEvolutionAction(
            title="test",
            description="test",
            risk="safe",
            patches=[candidate_patch],
        )

        from unittest.mock import MagicMock

        mock_review = MagicMock()
        mock_review.self_evolution_actions = [action]
        mock_review.build_actions = []
        mock_review.architecture_plans = []
        mock_review.execution_notes = []
        mock_review.risk_level = "low"
        mock_review.diagnosis = "test"

        monkeypatch.setattr(engine.reviewer, "review", lambda **_kw: mock_review)
        monkeypatch.setattr(engine.memory, "add_architecture_review", lambda _r: None)
        monkeypatch.setattr(engine.memory, "save", lambda: None)

        record = engine.run()

        events = [e.get("event") for e in record.trace]
        assert "safe_helper_lane_patch_generated" not in events

    def test_no_safe_patch_available_exits_cleanly_without_helper_targets(
        self, tmp_path, monkeypatch
    ):
        """When no helper targets exist at all, run() exits cleanly without crashing."""
        advice_path = _write_advice(tmp_path / "advice.json")
        monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

        from the_daddy.config import Settings
        from unittest.mock import MagicMock

        settings = Settings(
            target_root=tmp_path,
            command="python -c \"print('ok')\"",
        )
        engine = DaddyEngine(settings)

        mock_review = MagicMock()
        mock_review.self_evolution_actions = []
        mock_review.build_actions = []
        mock_review.architecture_plans = []
        mock_review.execution_notes = []
        mock_review.risk_level = "low"
        mock_review.diagnosis = "test"

        monkeypatch.setattr(engine.reviewer, "review", lambda **_kw: mock_review)
        monkeypatch.setattr(engine.memory, "add_architecture_review", lambda _r: None)
        monkeypatch.setattr(engine.memory, "save", lambda: None)

        record = engine.run()

        # Should not crash; record is still returned
        assert record is not None

    def test_helper_lane_patch_with_failing_command_fails_ci(self, tmp_path, monkeypatch):
        """Helper-lane patch that causes failing verification marks success=False."""
        _write_trace_summary(tmp_path)
        advice_path = _write_advice(tmp_path / "advice.json")
        monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

        from the_daddy.config import Settings
        from unittest.mock import MagicMock

        settings = Settings(
            target_root=tmp_path,
            command="python -c \"import sys; sys.exit(1)\"",
        )
        engine = DaddyEngine(settings)

        mock_review = MagicMock()
        mock_review.self_evolution_actions = []
        mock_review.build_actions = []
        mock_review.architecture_plans = []
        mock_review.execution_notes = []
        mock_review.risk_level = "low"
        mock_review.diagnosis = "test"

        monkeypatch.setattr(engine.reviewer, "review", lambda **_kw: mock_review)
        monkeypatch.setattr(engine.memory, "add_architecture_review", lambda _r: None)
        monkeypatch.setattr(engine.memory, "save", lambda: None)

        record = engine.run()

        assert record.success is False


# ---------------------------------------------------------------------------
# summarize_noop_repair_state unit tests
# ---------------------------------------------------------------------------

class TestSummarizeNoopRepairState:
    def test_repair_noop_true_when_no_safe_patch_summary(self):
        from the_daddy.runtime.trace_summary import summarize_noop_repair_state

        result = summarize_noop_repair_state(
            {"summary": "No safe repair patch available", "patch_count": 0, "success": False}
        )
        assert result["repair_noop"] is True
        assert result["patch_count"] == 0
        assert result["success"] is False

    def test_repair_noop_false_when_success(self):
        from the_daddy.runtime.trace_summary import summarize_noop_repair_state

        result = summarize_noop_repair_state(
            {"summary": "Success", "patch_count": 2, "success": True}
        )
        assert result["repair_noop"] is False
        assert result["patch_count"] == 2
        assert result["success"] is True

    def test_repair_noop_empty_payload(self):
        from the_daddy.runtime.trace_summary import summarize_noop_repair_state

        result = summarize_noop_repair_state({})
        assert result["repair_noop"] is False
        assert result["patch_count"] == 0
        assert result["success"] is False


# ---------------------------------------------------------------------------
# run_health.py deduplication tests
# ---------------------------------------------------------------------------

class TestRunHealthNoDuplicates:
    def test_run_health_has_exactly_one_recovery_tick_marker(self):
        import inspect
        import the_daddy.runtime.run_health as rh

        src = inspect.getsource(rh)
        assert src.count("def recovery_tick_marker(") == 1, (
            "Expected exactly one def recovery_tick_marker(), got multiple"
        )

    def test_run_health_has_exactly_one_recovery_tick_marker_v2(self):
        import inspect
        import the_daddy.runtime.run_health as rh

        src = inspect.getsource(rh)
        assert src.count("def recovery_tick_marker_v2(") == 1, (
            "Expected exactly one def recovery_tick_marker_v2(), got multiple"
        )

    def test_run_health_functions_are_callable(self):
        from the_daddy.runtime.run_health import (
            recovery_tick_marker,
            recovery_tick_marker_v2,
            summarize_run_health,
        )

        assert callable(summarize_run_health)
        assert callable(recovery_tick_marker)
        assert callable(recovery_tick_marker_v2)
        assert recovery_tick_marker()["status"] == "recovery_tick"
        assert recovery_tick_marker_v2()["status"] == "recovery_tick"


# ---------------------------------------------------------------------------
# summarize_repair_noop_ticks unit tests
# ---------------------------------------------------------------------------

class TestSummarizeRepairNoopTicks:
    def test_counts_noop_repairs(self):
        from the_daddy.runtime.run_health import summarize_repair_noop_ticks

        runs = [
            {"summary": "No safe repair patch available", "success": False},
            {"summary": "Success", "success": True},
            {"summary": "No safe repair patch available", "success": False},
        ]
        result = summarize_repair_noop_ticks(runs)
        assert result["noop_repair_count"] == 2
        assert result["total_runs"] == 3

    def test_empty_runs(self):
        from the_daddy.runtime.run_health import summarize_repair_noop_ticks

        result = summarize_repair_noop_ticks([])
        assert result["noop_repair_count"] == 0
        assert result["total_runs"] == 0

    def test_none_runs(self):
        from the_daddy.runtime.run_health import summarize_repair_noop_ticks

        result = summarize_repair_noop_ticks(None)
        assert result["noop_repair_count"] == 0


# ---------------------------------------------------------------------------
# Real-repo scenario: trace_summary already patched, run_health is available
# ---------------------------------------------------------------------------

class TestHelperLaneFallbackRealRepoScenario:
    def test_run_health_targeted_when_trace_summary_already_has_function(self, tmp_path, monkeypatch):
        """Simulates the real repo: trace_summary already has summarize_noop_repair_state,
        so the engine should fall back to run_health.py."""
        dest = tmp_path / "src" / "the_daddy" / "runtime"
        dest.mkdir(parents=True, exist_ok=True)
        # trace_summary already has the guard
        (dest / "trace_summary.py").write_text(
            "def summarize_noop_repair_state(run_payload): return {}\n",
            encoding="utf-8",
        )
        # run_health exists without the guard
        (dest / "run_health.py").write_text(
            "def summarize_run_health(runs=None): return {}\n"
            "def recovery_tick_marker(): return {}\n"
            "def recovery_tick_marker_v2(): return {}\n",
            encoding="utf-8",
        )

        advice_path = _write_advice(tmp_path / "advice.json")
        monkeypatch.setenv("DADDY_UPGRADE_ADVICE_PATH", str(advice_path))

        from the_daddy.config import Settings
        from unittest.mock import MagicMock

        settings = Settings(
            target_root=tmp_path,
            command="python -c \"print('ok')\"",
        )
        engine = DaddyEngine(settings)

        mock_review = MagicMock()
        mock_review.self_evolution_actions = []
        mock_review.build_actions = []
        mock_review.architecture_plans = []
        mock_review.execution_notes = []
        mock_review.risk_level = "low"
        mock_review.diagnosis = "test"

        monkeypatch.setattr(engine.reviewer, "review", lambda **_kw: mock_review)
        monkeypatch.setattr(engine.memory, "add_architecture_review", lambda _r: None)
        monkeypatch.setattr(engine.memory, "save", lambda: None)

        record = engine.run()

        events = [e.get("event") for e in record.trace]
        assert "safe_helper_lane_patch_generated" in events, (
            f"Expected safe_helper_lane_patch_generated. Trace events: {events}"
        )
        # Must target run_health, not trace_summary
        gen_event = next(
            e for e in record.trace if e.get("event") == "safe_helper_lane_patch_generated"
        )
        assert "run_health" in gen_event.get("chosen_path", ""), (
            f"Expected run_health as chosen_path, got: {gen_event}"
        )

