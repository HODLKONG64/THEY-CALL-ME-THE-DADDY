from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import the_daddy.engine as engine_module
from the_daddy.engine import DaddyEngine
from the_daddy.git_tools import GitBranchExecutor
from the_daddy.merge_rules import AutoMergeJudge
from the_daddy.core.request_upgrade_advice import build_learning_summary
from the_daddy.core.upgrade_gate import UpgradeGateError, validate_upgrade_advice
from the_daddy.memory.repository import MemoryRepository
from the_daddy.models import CommandResult, PatchAction, RunRecord
from the_daddy.policy import classify_patch_risk
from the_daddy.runtime.file_tools import apply_patch_action
from the_daddy.runtime.run_learning_ledger import build_run_learning_ledger_entry


def _settings(root: Path):
    from the_daddy.config import Settings

    s = Settings()
    s.target_root = root
    s.github_repo = ""
    s.github_token = ""
    return s


def main() -> int:
    out: dict[str, object] = {}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "src" / "the_daddy").mkdir(parents=True)
        (root / "src" / "the_daddy" / "cli.py").write_text("x=1\n", encoding="utf-8")
        (root / "src" / "the_daddy" / "runtime").mkdir(parents=True)
        (root / "src" / "the_daddy" / "runtime" / "trace_summary.py").write_text("x=1\n", encoding="utf-8")

        engine = DaddyEngine(_settings(root))
        record = RunRecord(run_id="stress", command="pytest -q")
        engine.upgrade_advice = {"target_files": ["src/the_daddy/cli.py"], "repair_mode": True}
        engine.repair_mode_active = True

        passing = PatchAction(
            path="src/the_daddy/runtime/trace_summary.py",
            operation="regex_replace",
            pattern=r"\Z",
            replacement="\n# stress-pass\n",
            description="pass",
        )
        failing = PatchAction(
            path="src/the_daddy/missing.py",
            operation="regex_replace",
            pattern=r"\Z",
            replacement="\n# stress-fail\n",
            description="fail",
        )

        applied_ok, rollback_ok, route_ok = engine._apply_safe_patches("stress-ok", "repair", [passing], record)
        out["applied_count"] = len(applied_ok)
        out["rollback_manifest_count"] = len(rollback_ok)
        out["passing_route"] = route_ok

        # Separate policy-rejection coverage: this failing patch is rejected before apply.
        failing_record = RunRecord(run_id="stress-fail", command="pytest -q")
        applied_fail, rollback_fail, route_fail = engine._apply_safe_patches("stress-fail", "repair", [failing], failing_record)
        out["policy_reject_failed_apply_count"] = len(applied_fail)
        out["policy_reject_failed_rollback_manifest_count"] = len(rollback_fail)
        out["policy_reject_route"] = route_fail
        out["policy_reject_patch_apply_failed_seen"] = any(
            e.get("event") == "patch_apply_failed" for e in failing_record.trace
        )

        # Real apply-path failure coverage: a policy-safe patch reaches apply and
        # fails inside apply_patch_action.
        apply_fail_target = root / "src" / "the_daddy" / "runtime" / "run_health.py"
        original_apply_fail_content = "base-health\n"
        apply_fail_target.write_text(original_apply_fail_content, encoding="utf-8")
        apply_fail_patch = PatchAction(
            path="src/the_daddy/runtime/run_health.py",
            operation="regex_replace",
            pattern=r"\Z",
            replacement="\n# stress-apply-failure\n",
            description="apply-failure-path",
        )

        original_apply_patch_action = engine_module.apply_patch_action

        def _failing_apply_patch_action(repo_root, patch, allow_extensions):
            if getattr(patch, "description", "") == "apply-failure-path":
                raise RuntimeError("injected apply failure")
            return original_apply_patch_action(repo_root, patch, allow_extensions)

        engine_module.apply_patch_action = _failing_apply_patch_action
        try:
            apply_fail_record = RunRecord(run_id="stress-apply-fail", command="pytest -q")
            apply_fail_applied, apply_fail_rollback, apply_fail_route = engine._apply_safe_patches(
                "stress-apply-fail", "repair", [apply_fail_patch], apply_fail_record
            )
        finally:
            engine_module.apply_patch_action = original_apply_patch_action

        out["apply_failure_route"] = apply_fail_route
        out["apply_failure_applied_count"] = len(apply_fail_applied)
        out["apply_failure_rollback_manifest_count"] = len(apply_fail_rollback)
        out["apply_failure_patch_apply_failed_seen"] = any(
            e.get("event") == "patch_apply_failed" for e in apply_fail_record.trace
        )
        out["apply_failure_file_unchanged"] = (
            apply_fail_target.read_text(encoding="utf-8") == original_apply_fail_content
        )
        out["readme_forbidden_rejected"] = not classify_patch_risk(
            [PatchAction(path="README.md", operation="regex_replace", pattern=r"\Z", replacement="\n", description="x")],
            upgrade_advice={"forbidden_repeat_patterns": ["readme heartbeat filler"], "target_files": []},
        ).passed
        out["merge_blocks_workflow"] = not AutoMergeJudge().should_auto_merge(
            success=True,
            policy_route="safe",
            changed_files=[".github/workflows/cycle.yml"],
            patch_count=1,
            total_byte_delta=10,
            review_risk="low",
        )[0]

        advice_base = {
            "summary": "x",
            "repo_state": "clean",
            "recommended_next_step": "repair",
            "target_files": ["src/the_daddy/cli.py"],
            "forbidden_repeat_patterns": [],
            "required_constraints": [],
            "tests_to_run": ["pytest -q"],
        }
        approved = root / "approved.json"
        approved.write_text(json.dumps({
            **advice_base,
            "allow_proceed": True,
            "problem_type": "healthy_meaningful_progress",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }), encoding="utf-8")
        out["approved_advice_ok"] = bool(validate_upgrade_advice(approved))

        stale = root / "stale.json"
        stale.write_text(json.dumps({
            **advice_base,
            "allow_proceed": True,
            "problem_type": "healthy_meaningful_progress",
            "generated_at": (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat(),
        }), encoding="utf-8")
        try:
            validate_upgrade_advice(stale)
            out["stale_advice_blocked"] = False
        except UpgradeGateError:
            out["stale_advice_blocked"] = True

        no_patch_record = RunRecord(run_id="stress-none", command="pytest -q")
        _, _, no_patch_route = engine._apply_safe_patches("stress-none", "repair", [], no_patch_record)
        out["no_patch_route"] = no_patch_route

        gbe = GitBranchExecutor(repo_root=root, github_token="t", github_repo="o/r")
        gbe._api_request = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("A pull request already exists"))  # type: ignore[attr-defined]
        gbe._find_existing_open_pr = lambda *_args, **_kwargs: {"number": 1, "html_url": "https://example/pr/1"}  # type: ignore[attr-defined]
        pr = gbe.create_pull_request("branch", "title", "body")
        out["existing_pr_reused"] = bool(pr and pr.get("number") == 1)

        direct_ok = apply_patch_action(root, passing, [".py", ".md", ".json", ".toml", ".yml", ".yaml", ".txt"])
        out["direct_passing_patch_applied"] = bool(direct_ok.get("bytes_after", 0) >= direct_ok.get("bytes_before", 0))
        try:
            apply_patch_action(root, failing, [".py", ".md", ".json", ".toml", ".yml", ".yaml", ".txt"])
            out["direct_failing_patch_blocked"] = False
        except Exception:
            out["direct_failing_patch_blocked"] = True

        # Learning ledger coverage.
        success_rec = RunRecord(run_id="ledger-success", command="pytest -q")
        success_rec.selected_mode = "repair"
        success_rec.success = True
        success_rec.patches_applied = [{"path": "src/the_daddy/cli.py", "description": "patch"}]
        success_rec.trace = [{"event": "patch_applied"}]
        success_rec.verification = CommandResult(returncode=0)
        success_entry = build_run_learning_ledger_entry(
            record=success_rec,
            upgrade_advice={"target_files": ["src/the_daddy/cli.py"]},
            policy_route="safe",
            proposed_patches=[passing],
            source="stress_harness",
        )

        blocked_noop_rec = RunRecord(run_id="ledger-noop", command="pytest -q")
        blocked_noop_rec.selected_mode = "repair"
        blocked_noop_rec.success = False
        blocked_noop_rec.trace = [{"event": "no_patch_blocker_recorded", "reason": "verification passed but no patch was applied"}]
        blocked_noop_rec.verification = CommandResult(returncode=0)
        blocked_noop_entry = build_run_learning_ledger_entry(
            record=blocked_noop_rec,
            upgrade_advice={"target_files": ["src/the_daddy/engine.py"]},
            policy_route="safe",
            proposed_patches=[],
            source="stress_harness",
        )

        advice_gap_rec = RunRecord(run_id="ledger-advice-gap", command="pytest -q")
        advice_gap_rec.selected_mode = "repair"
        advice_gap_rec.success = True
        advice_gap_rec.verification = CommandResult(returncode=0)
        advice_gap_entry = build_run_learning_ledger_entry(
            record=advice_gap_rec,
            upgrade_advice={"target_files": ["src/the_daddy/engine.py"]},
            policy_route="safe",
            proposed_patches=[],
            source="stress_harness",
        )

        clean_no_action_rec = RunRecord(run_id="ledger-clean-no-action", command="pytest -q")
        clean_no_action_rec.selected_mode = "architecture"
        clean_no_action_rec.success = True
        clean_no_action_rec.verification = CommandResult(returncode=0)
        clean_no_action_entry = build_run_learning_ledger_entry(
            record=clean_no_action_rec,
            upgrade_advice={"target_files": [], "recommended_next_step": "no_action"},
            policy_route="safe",
            proposed_patches=[],
            no_action_allowed=True,
            source="stress_harness",
        )

        learning_repo = MemoryRepository()
        for entry in [success_entry, blocked_noop_entry, advice_gap_entry, clean_no_action_entry]:
            learning_repo.add_run_learning_entry(entry)
        out["ledger_outcomes"] = [i.outcome for i in learning_repo.latest_run_learning_entries(limit=10)]
        out["ledger_recurring_blockers"] = learning_repo.ranked_recurring_blockers()
        out["ledger_learning_summary"] = learning_repo.summarize_recent_learning(limit=10)

        # Add a secret-like blocker and verify prompt-learning summary redacts it.
        secret_entry = build_run_learning_ledger_entry(
            record=blocked_noop_rec,
            upgrade_advice={"target_files": ["src/the_daddy/cli.py"]},
            policy_route="safe",
            proposed_patches=[],
            source="stress_harness",
        )
        secret_entry.blocked_reason = "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456"
        secret_entry.avoid_next_time = ["OPENAI_API_KEY=sk-super-secret-value"]
        learning_repo.add_run_learning_entry(secret_entry)
        local_state = root / "doctor_local"
        local_state.mkdir(parents=True, exist_ok=True)
        memory_path = local_state / "sam-memory.json"
        memory_path.write_text(json.dumps(learning_repo.snapshot(), indent=2), encoding="utf-8")
        prompt_summary = build_learning_summary(root)
        out["prompt_learning_summary"] = prompt_summary

        expected_outcomes = {
            "success_with_patch",
            "blocked_fake_noop",
            "advice_not_actionable",
            "clean_no_action",
        }
        observed_outcomes = set(str(x) for x in out["ledger_outcomes"])
        assert expected_outcomes.issubset(observed_outcomes), "missing expected ledger outcomes"

        stats = out["ledger_learning_summary"]["advice_actionability"]  # type: ignore[index]
        assert int(stats["verified_progress_count"]) == 1, "verified progress misclassified"
        assert int(stats["blocked_or_failed_count"]) >= 1, "blocked/failed not counted"

        summary_blob = json.dumps(prompt_summary)
        assert "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456" not in summary_blob, "prompt summary leaked auth token"
        assert "sk-super-secret-value" not in summary_blob, "prompt summary leaked api key"
        assert "[REDACTED" in summary_blob, "redaction marker missing from prompt summary"
        assert len(summary_blob) < 12000, "prompt summary payload too large"

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
