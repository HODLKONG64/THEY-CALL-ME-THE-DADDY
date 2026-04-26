"""Tests for the meaningful helper-lane upgrade.

Covers the required behavior:
- helper-lane prefers tests (tier A) over docs (tier C)
- helper-lane never targets README.md, engine.py, or cli.py
- meaningful_helper_lane_patch_generated appears in trace
- generated patch content is valid and passes a syntax check
- fallback exits cleanly if no safe target exists
- safe_helper_lane_patch_generated and helper_lane_attempted remain present
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from the_daddy.engine import (
    SAFE_HELPER_LANE_TARGETS,
    DaddyEngine,
    make_run_id,
)
from the_daddy.models import RunRecord


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


def _make_engine(tmp_path: Path) -> DaddyEngine:
    return DaddyEngine(_make_settings(tmp_path))


def _make_record() -> RunRecord:
    return RunRecord(run_id=make_run_id(), command="pytest -q")


def _set_healthy_safe_loop(engine: DaddyEngine) -> None:
    engine.upgrade_advice = {
        "target_files": ["src/the_daddy/engine.py"],
        "repair_mode": True,
        "problem_type": "healthy_safe_loop",
        "allow_proceed": False,
    }
    engine.repair_mode_active = True


def _write_test_file(tmp_path: Path) -> Path:
    """Write a basic test_repair_fallback.py file to tmp_path."""
    dest = tmp_path / "tests"
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "test_repair_fallback.py"
    target.write_text(
        "from the_daddy.engine import DaddyEngine, make_run_id\n"
        "from the_daddy.models import RunRecord\n"
        "\n\n"
        "def _make_settings_with_root(tmp_path):\n"
        "    from the_daddy.config import Settings\n"
        "    s = Settings()\n"
        "    s.target_root = tmp_path\n"
        "    s.github_repo = ''\n"
        "    s.github_token = ''\n"
        "    return s\n"
        "\n\n"
        "def _make_record():\n"
        "    return RunRecord(run_id=make_run_id(), command='pytest -q')\n",
        encoding="utf-8",
    )
    return target


def _write_docs_file(tmp_path: Path) -> Path:
    """Write a minimal ARCHITECTURE.md to tmp_path."""
    dest = tmp_path / "docs"
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "ARCHITECTURE.md"
    target.write_text(
        "# Architecture\n\nSystem overview.\n",
        encoding="utf-8",
    )
    return target


# ---------------------------------------------------------------------------
# Tier preference tests
# ---------------------------------------------------------------------------

class TestHelperLaneTierPreference:
    def test_prefers_test_over_docs(self, tmp_path):
        """When both a test file (tier A) and a docs file (tier C) are present,
        helper-lane must pick the test file."""
        _write_test_file(tmp_path)
        _write_docs_file(tmp_path)

        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert len(patches) == 1
        assert patches[0].path.startswith("tests/"), (
            f"Expected tier-A test file, got: {patches[0].path}"
        )

    def test_prefers_test_over_runtime(self, tmp_path):
        """When both a test file (tier A) and a runtime file (tier B) are
        present, helper-lane must pick the test file — tier-A is ALWAYS first."""
        _write_test_file(tmp_path)
        # Write a runtime file that also has an eligible (missing) guard
        runtime_dest = tmp_path / "src" / "the_daddy" / "runtime"
        runtime_dest.mkdir(parents=True, exist_ok=True)
        (runtime_dest / "trace_summary.py").write_text(
            "def summarize_trace(trace): return {}\n",
            encoding="utf-8",
        )

        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert len(patches) == 1
        assert patches[0].path.startswith("tests/"), (
            f"Expected tier-A test file, got: {patches[0].path}"
        )
        evt = next(
            (e for e in record.trace if e.get("event") == "meaningful_helper_lane_patch_generated"),
            None,
        )
        assert evt is not None
        assert evt["tier"] == "A"

    def test_falls_back_to_runtime_when_no_test_target(self, tmp_path):
        """When only a runtime file exists, helper-lane picks it (tier B)."""
        runtime_dest = tmp_path / "src" / "the_daddy" / "runtime"
        runtime_dest.mkdir(parents=True, exist_ok=True)
        (runtime_dest / "trace_summary.py").write_text(
            "def summarize_trace(trace): return {}\n",
            encoding="utf-8",
        )

        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert len(patches) == 1
        assert patches[0].path.startswith("src/the_daddy/runtime/"), (
            f"Expected tier-B runtime file, got: {patches[0].path}"
        )
        evt = next(
            (e for e in record.trace if e.get("event") == "meaningful_helper_lane_patch_generated"),
            None,
        )
        assert evt is not None
        assert evt["tier"] == "B"

    def test_falls_back_to_docs_when_no_test_or_runtime_target(self, tmp_path):
        """When only a docs file exists, helper-lane picks the docs file."""
        _write_docs_file(tmp_path)

        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert len(patches) == 1
        assert patches[0].path.startswith("docs/"), (
            f"Expected tier-C docs file, got: {patches[0].path}"
        )

    def test_tier_a_chosen_path_in_trace(self, tmp_path):
        """When a test file is picked, trace must record the test path as chosen_path."""
        _write_test_file(tmp_path)

        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        engine._build_safe_helper_lane_patch(record)

        evt = next(
            (e for e in record.trace if e.get("event") == "meaningful_helper_lane_patch_generated"),
            None,
        )
        assert evt is not None
        assert evt["chosen_path"].startswith("tests/")
        assert evt["tier"] == "A"

    def test_safe_helper_lane_targets_derived_from_candidates(self):
        """SAFE_HELPER_LANE_TARGETS must be derived from _HELPER_LANE_CANDIDATES
        (single source of truth — no separate manual list)."""
        from the_daddy.engine import _HELPER_LANE_CANDIDATES

        derived = [entry[0] for entry in _HELPER_LANE_CANDIDATES]
        assert SAFE_HELPER_LANE_TARGETS == derived, (
            "SAFE_HELPER_LANE_TARGETS diverged from _HELPER_LANE_CANDIDATES paths"
        )

    def test_candidates_tier_order_is_a_then_b_then_c(self):
        """All tier-A entries must appear before all tier-B entries, which must
        appear before all tier-C entries in _HELPER_LANE_CANDIDATES."""
        from the_daddy.engine import _HELPER_LANE_CANDIDATES

        tier_order = {"A": 0, "B": 1, "C": 2}
        tiers = [entry[3] for entry in _HELPER_LANE_CANDIDATES]
        last_rank = -1
        for t in tiers:
            rank = tier_order.get(t, -1)
            assert rank >= 0, f"Unknown tier {t!r} in _HELPER_LANE_CANDIDATES"
            assert rank >= last_rank, (
                f"Tier order violation: tier {t!r} (rank {rank}) follows a "
                f"higher-rank tier (rank {last_rank})"
            )
            last_rank = rank


# ---------------------------------------------------------------------------
# Forbidden target tests
# ---------------------------------------------------------------------------

class TestHelperLaneForbiddenTargets:
    def test_never_targets_readme(self, tmp_path):
        _write_test_file(tmp_path)
        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert all("readme" not in p.path.lower() for p in patches)
        assert all(p.path != "README.md" for p in patches)

    def test_never_targets_engine_py(self, tmp_path):
        _write_test_file(tmp_path)
        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert all(p.path != "src/the_daddy/engine.py" for p in patches)

    def test_never_targets_cli_py(self, tmp_path):
        _write_test_file(tmp_path)
        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert all(p.path != "src/the_daddy/cli.py" for p in patches)

    def test_safe_helper_lane_targets_constant_never_has_readme(self):
        for t in SAFE_HELPER_LANE_TARGETS:
            assert "readme" not in t.lower(), f"README found in targets: {t}"

    def test_safe_helper_lane_targets_constant_never_has_engine_py(self):
        assert "src/the_daddy/engine.py" not in SAFE_HELPER_LANE_TARGETS

    def test_safe_helper_lane_targets_constant_never_has_cli_py(self):
        assert "src/the_daddy/cli.py" not in SAFE_HELPER_LANE_TARGETS


# ---------------------------------------------------------------------------
# meaningful_helper_lane_patch_generated trace event
# ---------------------------------------------------------------------------

class TestMeaningfulHelperLaneTraceEvent:
    def test_meaningful_event_in_trace_when_patch_generated(self, tmp_path):
        """meaningful_helper_lane_patch_generated must appear in trace."""
        _write_test_file(tmp_path)
        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        engine._build_safe_helper_lane_patch(record)

        events = [e.get("event") for e in record.trace]
        assert "meaningful_helper_lane_patch_generated" in events

    def test_meaningful_event_has_required_fields(self, tmp_path):
        """meaningful_helper_lane_patch_generated must include chosen_path, tier, guard_symbol, run_id."""
        _write_test_file(tmp_path)
        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        engine._build_safe_helper_lane_patch(record)

        evt = next(
            (e for e in record.trace if e.get("event") == "meaningful_helper_lane_patch_generated"),
            None,
        )
        assert evt is not None
        assert "chosen_path" in evt
        assert "tier" in evt
        assert "guard_symbol" in evt
        assert "run_id" in evt

    def test_legacy_safe_event_still_emitted(self, tmp_path):
        """safe_helper_lane_patch_generated must still be emitted for backward compatibility."""
        _write_test_file(tmp_path)
        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        engine._build_safe_helper_lane_patch(record)

        events = [e.get("event") for e in record.trace]
        assert "safe_helper_lane_patch_generated" in events

    def test_no_meaningful_event_when_no_patch_available(self, tmp_path):
        """When no target exists, meaningful_helper_lane_patch_generated must NOT appear."""
        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        engine._build_safe_helper_lane_patch(record)

        events = [e.get("event") for e in record.trace]
        assert "meaningful_helper_lane_patch_generated" not in events
        assert "safe_helper_lane_patch_unavailable" in events


# ---------------------------------------------------------------------------
# Patch validity: applies and produces valid content
# ---------------------------------------------------------------------------

class TestHelperLanePatchValidity:
    def test_patch_applies_and_is_valid_python(self, tmp_path):
        """Generated test-tier patch produces syntactically valid Python when applied."""
        test_file = _write_test_file(tmp_path)
        original = test_file.read_text(encoding="utf-8")

        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert len(patches) == 1
        p = patches[0]
        assert p.path.startswith("tests/")

        # Apply the regex_replace
        result = re.sub(p.pattern, p.replacement, original, flags=re.MULTILINE | re.DOTALL)

        # Result must be valid Python
        try:
            compile(result, "<string>", "exec")
        except SyntaxError as exc:
            pytest.fail(f"Patch produces invalid Python: {exc}\n\nResult:\n{result}")

        # Guard symbol must be present in result
        assert "test_repair_mode_helper_lane_regression" in result

    def test_patch_is_under_40_changed_lines(self, tmp_path):
        """Each helper-lane patch must be under 40 changed lines."""
        _write_test_file(tmp_path)
        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert len(patches) == 1
        addition = patches[0].replacement or ""
        line_count = len(addition.splitlines())
        assert line_count <= 40, (
            f"Patch exceeds 40 lines ({line_count} lines). Replacement:\n{addition}"
        )

    def test_patch_is_reversible(self, tmp_path):
        """Patch uses append-only regex_replace (pattern=r'\\Z'), making it reversible."""
        _write_test_file(tmp_path)
        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert len(patches) == 1
        assert patches[0].pattern == r"\Z", (
            f"Expected append-only pattern r'\\Z', got: {patches[0].pattern!r}"
        )


# ---------------------------------------------------------------------------
# Fallback clean exit when no safe target exists
# ---------------------------------------------------------------------------

class TestHelperLaneFallbackCleanExit:
    def test_exits_cleanly_no_crash(self, tmp_path):
        """When no helper target exists, _build_safe_helper_lane_patch returns [] without raising."""
        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        patches = engine._build_safe_helper_lane_patch(record)

        assert patches == []
        assert record is not None

    def test_safe_helper_lane_patch_unavailable_event_emitted(self, tmp_path):
        """When no target exists, safe_helper_lane_patch_unavailable event is emitted."""
        engine = _make_engine(tmp_path)
        _set_healthy_safe_loop(engine)
        record = _make_record()

        engine._build_safe_helper_lane_patch(record)

        events = [e.get("event") for e in record.trace]
        assert "safe_helper_lane_patch_unavailable" in events


# ---------------------------------------------------------------------------
# Integration: helper_lane_attempted result=success still works
# ---------------------------------------------------------------------------

class TestHelperLaneAttemptedEvent:
    def test_helper_lane_attempted_result_success(self, tmp_path, monkeypatch):
        """Full run(): helper_lane_attempted with result=success must be in trace."""
        _write_test_file(tmp_path)
        from datetime import datetime, timezone
        import json

        advice = {
            "allow_proceed": False,
            "summary": "safe loop",
            "repo_state": "test",
            "problem_type": "healthy_safe_loop",
            "recommended_next_step": "bounded patch",
            "target_files": ["src/the_daddy/engine.py"],
            "forbidden_repeat_patterns": [],
            "required_constraints": [],
            "tests_to_run": ["pytest -q"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        advice_path = tmp_path / "advice.json"
        advice_path.write_text(json.dumps(advice), encoding="utf-8")
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
        assert "helper_lane_attempted" in events
        attempted_evt = next(e for e in record.trace if e.get("event") == "helper_lane_attempted")
        assert attempted_evt["result"] == "success"
        assert "meaningful_helper_lane_patch_generated" in events
