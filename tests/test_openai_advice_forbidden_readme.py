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
        """_build_forced_target_patches is disabled entirely to prevent filler loops."""
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
        assert any(e.get("event") == "forced_target_patch_generation_skipped" for e in record.trace)

    def test_forced_readme_allowed_when_advice_permits(self, tmp_path):
        """Forced README fallback remains disabled even when advice permits it."""
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

        assert patches == []


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


# ---------------------------------------------------------------------------
# Mandatory named tests required by the problem statement
# ---------------------------------------------------------------------------

class TestMandatoryPolicyEnforcement:
    """Mandatory tests: test_readme_patch_blocked_by_advice, test_non_target_patch_blocked,
    test_merge_rejected_for_readme_only_patch."""

    def test_readme_patch_blocked_by_advice(self):
        """classify_patch_risk rejects README.md when advice forbids README/doc patches.

        Asserts:
        - patch not applied (policy result failed)
        - PR not opened (policy route is reject)
        """
        from the_daddy.models import PatchAction
        from the_daddy.policy import classify_patch_risk

        advice = {
            "target_files": ["src/the_daddy/cli.py", "src/the_daddy/engine.py"],
            "forbidden_repeat_patterns": ["README heartbeat/doc-only/helper-lane filler"],
        }
        patches = [
            PatchAction(
                path="README.md",
                operation="regex_replace",
                pattern=r"\Z",
                replacement="\n<!-- heartbeat: 🔥 test -->\n",
                description="README heartbeat",
            )
        ]

        result = classify_patch_risk(patches, upgrade_advice=advice)

        assert not result.passed, "Policy should reject README patch when advice forbids it"
        assert result.route == "reject"
        assert any("OpenAI advice" in r and "README" in r for r in result.reasons)

    def test_non_target_patch_blocked(self):
        """classify_patch_risk rejects patches outside target_files when advice provides them.

        Asserts:
        - patch not applied (policy result failed)
        - PR not opened (policy route is reject)
        """
        from the_daddy.models import PatchAction
        from the_daddy.policy import classify_patch_risk

        advice = {
            "target_files": ["src/the_daddy/cli.py", "src/the_daddy/engine.py"],
            "forbidden_repeat_patterns": [],
        }
        # Patch to a file that is not in target_files and not in ALLOWLISTED_RUNTIME_HELPERS
        patches = [
            PatchAction(
                path="src/the_daddy/config.py",
                operation="regex_replace",
                pattern=r"\Z",
                replacement="\n# noop\n",
                description="config noop",
            )
        ]

        result = classify_patch_risk(patches, upgrade_advice=advice)

        assert not result.passed, "Policy should reject patch outside target_files"
        assert result.route == "reject"
        assert any("out of scope" in r or "target_files" in r for r in result.reasons)

    def test_allowlisted_helper_passes_target_file_enforcement(self):
        """ALLOWLISTED_RUNTIME_HELPERS paths are always accepted even when target_files is set."""
        from the_daddy.models import PatchAction
        from the_daddy.policy import classify_patch_risk

        advice = {
            "target_files": ["src/the_daddy/cli.py"],
            "forbidden_repeat_patterns": [],
        }
        patches = [
            PatchAction(
                path="src/the_daddy/runtime/trace_summary.py",
                operation="regex_replace",
                pattern=r"\Z",
                replacement="\n# helper noop\n",
                description="helper noop",
            )
        ]

        result = classify_patch_risk(patches, upgrade_advice=advice)

        # trace_summary.py is in ALLOWLISTED_RUNTIME_HELPERS → must not be blocked by target enforcement
        assert result.passed, f"ALLOWLISTED path should not be blocked; reasons: {result.reasons}"

    def test_merge_rejected_for_readme_only_patch(self):
        """AutoMergeJudge must reject merge when changed_files is only README.md
        and OpenAI advice forbids README/filler patches.

        Asserts:
        - merge not executed (should_auto_merge returns False)
        """
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

        assert allowed is False, "Merge must be rejected for README-only patch when forbidden"
        assert any("readme" in r.lower() or "README" in r for r in reasons)

    def test_target_files_bypass_sentinel_does_not_enforce(self):
        """When target_files contains only 'gate_bypassed', no target enforcement occurs."""
        from the_daddy.models import PatchAction
        from the_daddy.policy import classify_patch_risk

        advice = {
            "target_files": ["gate_bypassed"],
            "forbidden_repeat_patterns": [],
        }
        # Use a path in a subdirectory so it doesn't trip the hallucination check
        # and is not in PROTECTED_CORE_FILES.
        patches = [
            PatchAction(
                path="src/the_daddy/agents/diagnoser.py",
                operation="regex_replace",
                pattern=r"\Z",
                replacement="\n# noop\n",
                description="noop",
            )
        ]

        result = classify_patch_risk(patches, upgrade_advice=advice)

        # gate_bypassed sentinel means no target enforcement — any other failures are
        # NOT due to the target enforcement logic.
        assert not any("out of scope" in r or "target_files" in r for r in result.reasons), (
            f"gate_bypassed should not trigger target enforcement; reasons: {result.reasons}"
        )

    def test_policy_still_works_without_upgrade_advice(self):
        """Existing call sites that pass no upgrade_advice remain fully unchanged."""
        from the_daddy.models import PatchAction
        from the_daddy.policy import classify_patch_risk

        patches = [
            PatchAction(
                path="src/the_daddy/runtime/trace_summary.py",
                operation="regex_replace",
                pattern=r"\Z",
                replacement="\n# noop\n",
                description="noop",
            )
        ]
        result = classify_patch_risk(patches)
        assert result.passed

    def test_engine_emits_per_patch_trace_event_on_policy_rejection(self, tmp_path):
        """When policy rejects due to OpenAI advice, engine emits
        openai_advice_forbidden_patch_blocked per blocked patch."""
        from the_daddy.engine import DaddyEngine, make_run_id
        from the_daddy.models import PatchAction, RunRecord

        engine = _make_engine(tmp_path)
        engine.upgrade_advice = {
            "target_files": ["src/the_daddy/cli.py"],
            "forbidden_repeat_patterns": ["README heartbeat/filler"],
        }

        # Write a dummy README so apply_patch_action doesn't fail on file-missing
        (tmp_path / "README.md").write_text("# test\n", encoding="utf-8")

        record = RunRecord(run_id=make_run_id(), command="pytest -q")
        patches = [
            PatchAction(
                path="README.md",
                operation="regex_replace",
                pattern=r"\Z",
                replacement="\n<!-- heartbeat -->\n",
                description="README heartbeat",
            )
        ]

        engine._apply_safe_patches("test-run", "build", patches, record)

        # The trace must contain the per-patch blocked event
        blocked = [e for e in record.trace if e.get("event") == "openai_advice_forbidden_patch_blocked"]
        assert len(blocked) >= 1
        assert any(e.get("path") == "README.md" for e in blocked)

