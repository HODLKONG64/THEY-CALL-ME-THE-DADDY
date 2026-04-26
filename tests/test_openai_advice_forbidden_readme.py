"""Tests proving that README-only patches are rejected when OpenAI upgrade
advice explicitly forbids README/doc-only/filler patterns.

Covered requirements:
1. README-only patch is rejected (not produced) when advice forbids README.
2. PR is not opened in that path.
3. PR is not merged in that path.
4. changed_files cannot be README.md when the advice forbids it.
5. openai_advice_forbidden_patch_blocked trace event is emitted.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from the_daddy.engine import DaddyEngine, _README_FORBIDDEN_KEYWORDS, make_run_id
from the_daddy.merge_rules import AutoMergeJudge
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


def _advice_with_forbidden_readme(*, allow_proceed: bool = True) -> dict[str, Any]:
    """Return upgrade advice whose forbidden_repeat_patterns forbid README patches."""
    from datetime import datetime, timezone

    return {
        "allow_proceed": allow_proceed,
        "summary": "approved",
        "repo_state": "test_repo_state",
        "problem_type": "healthy_meaningful_progress",
        "recommended_next_step": "none",
        "target_files": ["src/the_daddy/cli.py", "src/the_daddy/engine.py"],
        "forbidden_repeat_patterns": [
            "README heartbeat/doc-only/helper-lane filler",
        ],
        "required_constraints": [],
        "tests_to_run": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _advice_without_forbidden_readme() -> dict[str, Any]:
    """Return upgrade advice with no README-related forbidden patterns."""
    from datetime import datetime, timezone

    return {
        "allow_proceed": True,
        "summary": "approved",
        "repo_state": "test_repo_state",
        "problem_type": "healthy_meaningful_progress",
        "recommended_next_step": "none",
        "target_files": ["src/the_daddy/engine.py"],
        "forbidden_repeat_patterns": ["no filler patches"],
        "required_constraints": [],
        "tests_to_run": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# _advice_forbids_readme unit tests
# ---------------------------------------------------------------------------

class TestAdviceForbidsReadme:
    def test_returns_false_with_no_advice(self, tmp_path):
        engine = _make_engine(tmp_path)
        assert engine._advice_forbids_readme() is False

    def test_returns_false_when_forbidden_patterns_empty(self, tmp_path):
        engine = _make_engine(tmp_path)
        engine.upgrade_advice = {"forbidden_repeat_patterns": []}
        assert engine._advice_forbids_readme() is False

    def test_returns_false_when_no_readme_keyword(self, tmp_path):
        engine = _make_engine(tmp_path)
        engine.upgrade_advice = {"forbidden_repeat_patterns": ["do not break imports"]}
        assert engine._advice_forbids_readme() is False

    def test_returns_true_for_readme_heartbeat_pattern(self, tmp_path):
        engine = _make_engine(tmp_path)
        engine.upgrade_advice = {
            "forbidden_repeat_patterns": ["README heartbeat/doc-only/helper-lane filler"]
        }
        assert engine._advice_forbids_readme() is True

    def test_returns_true_for_doc_only_pattern(self, tmp_path):
        engine = _make_engine(tmp_path)
        engine.upgrade_advice = {"forbidden_repeat_patterns": ["doc-only patches"]}
        assert engine._advice_forbids_readme() is True

    def test_returns_true_for_filler_pattern(self, tmp_path):
        engine = _make_engine(tmp_path)
        engine.upgrade_advice = {"forbidden_repeat_patterns": ["no filler patches allowed"]}
        assert engine._advice_forbids_readme() is True

    def test_returns_true_case_insensitive(self, tmp_path):
        engine = _make_engine(tmp_path)
        engine.upgrade_advice = {"forbidden_repeat_patterns": ["README HEARTBEAT"]}
        assert engine._advice_forbids_readme() is True

    def test_readme_forbidden_keywords_constant_covers_known_patterns(self):
        """Ensure the constant covers all documented forbidden keywords."""
        for kw in ("readme", "doc-only", "filler", "heartbeat", "helper-lane filler"):
            assert kw in _README_FORBIDDEN_KEYWORDS, f"Missing keyword: {kw}"


# ---------------------------------------------------------------------------
# README heartbeat suppression when advice forbids README
# ---------------------------------------------------------------------------

class TestReadmeHeartbeatSuppressed:
    def test_heartbeat_not_added_when_advice_forbids_readme(self, tmp_path):
        """Non-repair mode must NOT append README heartbeat when forbidden."""
        (tmp_path / "README.md").write_text("# test\n", encoding="utf-8")
        engine = _make_engine(tmp_path)
        engine.upgrade_advice = _advice_with_forbidden_readme()
        engine.repair_mode_active = False
        record = _make_record()

        # Simulate what the run() loop does for the heartbeat block
        patches = []
        if engine._advice_forbids_readme():
            record.trace.append(
                {
                    "event": "openai_advice_forbidden_patch_blocked",
                    "reason": "forbidden_repeat_patterns forbids README/doc-only/heartbeat patches",
                    "blocked_path": "README.md",
                }
            )
        else:
            patches.extend(engine._build_readme_heartbeat_patch("🛠️", record.run_id))

        assert patches == []
        assert any(
            e.get("event") == "openai_advice_forbidden_patch_blocked" for e in record.trace
        ), "Expected openai_advice_forbidden_patch_blocked trace event"

    def test_heartbeat_still_added_when_advice_allows_readme(self, tmp_path):
        """README heartbeat SHOULD still be added when advice has no README ban."""
        (tmp_path / "README.md").write_text("# test\n", encoding="utf-8")
        engine = _make_engine(tmp_path)
        engine.upgrade_advice = _advice_without_forbidden_readme()
        engine.repair_mode_active = False

        patches = engine._build_readme_heartbeat_patch("🛠️", "test-run")
        assert len(patches) == 1
        assert patches[0].path == "README.md"


# ---------------------------------------------------------------------------
# _build_forced_target_patches suppression
# ---------------------------------------------------------------------------

class TestForcedTargetPatchesSuppressed:
    def test_forced_readme_blocked_when_advice_forbids(self, tmp_path):
        """_build_forced_target_patches must return [] when README is forbidden."""
        (tmp_path / "README.md").write_text("# test\n", encoding="utf-8")
        engine = _make_engine(tmp_path)
        engine.upgrade_advice = {
            **_advice_with_forbidden_readme(),
            "target_files": ["src/the_daddy/engine.py"],
            "repair_mode": True,
        }
        engine.repair_mode_active = True
        record = _make_record()

        patches = engine._build_forced_target_patches(record)

        assert patches == []
        blocked_events = [
            e for e in record.trace
            if e.get("event") == "openai_advice_forbidden_patch_blocked"
        ]
        assert len(blocked_events) >= 1
        assert any(
            "readme" in str(e.get("reason", "")).lower()
            for e in blocked_events
        )

    def test_forced_readme_allowed_when_advice_permits(self, tmp_path):
        """_build_forced_target_patches proceeds normally when README is not forbidden."""
        (tmp_path / "README.md").write_text("# test\n", encoding="utf-8")
        engine = _make_engine(tmp_path)
        engine.upgrade_advice = {
            "allow_proceed": True,
            "target_files": ["src/the_daddy/engine.py"],
            "repair_mode": True,
            "forbidden_repeat_patterns": [],
            "problem_type": "healthy_meaningful_progress",
        }
        engine.repair_mode_active = True
        record = _make_record()

        patches = engine._build_forced_target_patches(record)

        assert len(patches) == 1
        assert patches[0].path == "README.md"


# ---------------------------------------------------------------------------
# PR delivery blocked for README-only when forbidden
# ---------------------------------------------------------------------------

class TestDeliverPatchViaPrReadmeBlocked:
    def test_pr_not_opened_for_readme_only_when_forbidden(self, tmp_path):
        """_deliver_patch_via_pr must skip PR when all changed files are README.md
        and the advice forbids README patches."""
        engine = _make_engine(tmp_path)
        engine.upgrade_advice = _advice_with_forbidden_readme()

        record = _make_record()
        record.patches_applied = [
            {"path": "README.md", "description": "heartbeat", "bytes_before": 10, "bytes_after": 50}
        ]
        record.success = True

        pr_open_calls = []

        class FakeGitTools:
            def prepare_branch(self, run_id):
                return "test-branch"

            def commit_current_branch_changes(self, run_id, files):
                return "test-branch"

            def create_pull_request(self, **kwargs):
                pr_open_calls.append(kwargs)
                return {"number": 99, "html_url": "https://example.com/pr/99"}

        engine.git_tools = FakeGitTools()

        engine._deliver_patch_via_pr(record, "safe")

        # PR must NOT have been opened
        assert pr_open_calls == [], "PR should not be opened for README-only forbidden patch"

        # Must have emitted the forbidden-patch-blocked trace event
        assert any(
            e.get("event") == "openai_advice_forbidden_patch_blocked" for e in record.trace
        )

        # Must have emitted pr_skipped with the correct reason
        skipped = [e for e in record.trace if e.get("event") == "pr_skipped"]
        assert any(
            e.get("reason") == "readme_only_forbidden_by_advice" for e in skipped
        )

    def test_changed_files_cannot_be_readme_when_forbidden(self, tmp_path):
        """When the advice forbids README, the final changed_files in patches_applied
        must NOT contain only README.md after a run block."""
        engine = _make_engine(tmp_path)
        engine.upgrade_advice = _advice_with_forbidden_readme()

        record = _make_record()
        # Simulate a scenario where only README.md patches were applied
        record.patches_applied = [
            {"path": "README.md", "description": "heartbeat", "bytes_before": 10, "bytes_after": 53}
        ]
        record.success = True

        pr_open_calls = []
        merge_calls = []

        class FakeGitTools:
            def prepare_branch(self, run_id):
                return "test-branch"

            def commit_current_branch_changes(self, run_id, files):
                return "test-branch"

            def create_pull_request(self, **kwargs):
                pr_open_calls.append(kwargs)
                return {"number": 100, "html_url": "https://example.com/pr/100"}

            def merge_pull_request(self, **kwargs):
                merge_calls.append(kwargs)
                return {"merged": True}

        engine.git_tools = FakeGitTools()

        engine._deliver_patch_via_pr(record, "safe")

        # Neither PR opened nor merged
        assert pr_open_calls == []
        assert merge_calls == []

    def test_pr_opened_when_readme_not_sole_changed_file(self, tmp_path):
        """If changed files include both README.md and another file, PR delivery
        proceeds normally (README ban is only for README-exclusive patches)."""
        engine = _make_engine(tmp_path)
        engine.upgrade_advice = _advice_with_forbidden_readme()

        record = _make_record()
        record.patches_applied = [
            {"path": "README.md", "description": "hb", "bytes_before": 10, "bytes_after": 50},
            {"path": "src/the_daddy/cli.py", "description": "probe", "bytes_before": 100, "bytes_after": 110},
        ]
        record.success = True

        pr_open_calls = []

        class FakeGitTools:
            def prepare_branch(self, run_id):
                return "test-branch"

            def commit_current_branch_changes(self, run_id, files):
                return "test-branch"

            def create_pull_request(self, **kwargs):
                pr_open_calls.append(kwargs)
                return {"number": 101, "html_url": "https://example.com/pr/101"}

            def merge_pull_request(self, **kwargs):
                return {}

        engine.git_tools = FakeGitTools()
        engine._deliver_patch_via_pr(record, "safe")

        # PR should have been created
        assert len(pr_open_calls) == 1

    def test_pr_not_merged_when_readme_only_forbidden(self, tmp_path):
        """Even if PR is somehow created, merge_judgement must block README-only
        patches when advice forbids them (defence in depth via AutoMergeJudge)."""
        judge = AutoMergeJudge()
        allowed, reasons = judge.should_auto_merge(
            success=True,
            policy_route="safe",
            changed_files=["README.md"],
            patch_count=1,
            total_byte_delta=43,
            review_risk="low",
            readme_patch_forbidden=True,
        )
        assert allowed is False
        assert any("readme" in r.lower() for r in reasons)

class TestAutoMergeJudgeReadmeForbidden:
    def test_blocks_readme_only_when_forbidden(self):
        judge = AutoMergeJudge()
        allowed, reasons = judge.should_auto_merge(
            success=True,
            policy_route="safe",
            changed_files=["README.md"],
            patch_count=1,
            total_byte_delta=10,
            review_risk="low",
            readme_patch_forbidden=True,
        )
        assert allowed is False
        assert any("readme" in r.lower() for r in reasons)

    def test_does_not_block_non_readme_when_forbidden_flag_set(self):
        """readme_patch_forbidden=True should not affect non-README patches."""
        judge = AutoMergeJudge()
        allowed, reasons = judge.should_auto_merge(
            success=True,
            policy_route="safe",
            changed_files=["src/the_daddy/runtime/trace_summary.py"],
            patch_count=1,
            total_byte_delta=10,
            review_risk="low",
            readme_patch_forbidden=True,
        )
        assert allowed is True

    def test_does_not_block_readme_when_not_forbidden(self):
        """Without the flag, README-only auto-merge proceeds as normal."""
        judge = AutoMergeJudge()
        allowed, reasons = judge.should_auto_merge(
            success=True,
            policy_route="safe",
            changed_files=["README.md"],
            patch_count=1,
            total_byte_delta=10,
            review_risk="low",
            readme_patch_forbidden=False,
        )
        # Should be allowed (no other blocking reason)
        assert allowed is True

    def test_default_readme_patch_forbidden_is_false(self):
        """readme_patch_forbidden defaults to False – existing call sites unchanged."""
        judge = AutoMergeJudge()
        allowed, _ = judge.should_auto_merge(
            success=True,
            policy_route="safe",
            changed_files=["README.md"],
            patch_count=1,
            total_byte_delta=10,
            review_risk="low",
        )
        assert allowed is True
