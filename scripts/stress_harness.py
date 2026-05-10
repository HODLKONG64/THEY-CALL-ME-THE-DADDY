from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from the_daddy.engine import DaddyEngine
from the_daddy.git_tools import GitBranchExecutor
from the_daddy.merge_rules import AutoMergeJudge
from the_daddy.core.upgrade_gate import UpgradeGateError, validate_upgrade_advice
from the_daddy.models import PatchAction, RunRecord
from the_daddy.policy import classify_patch_risk
from the_daddy.runtime.file_tools import apply_patch_action


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

        failing_record = RunRecord(run_id="stress-fail", command="pytest -q")
        applied_fail, rollback_fail, route_fail = engine._apply_safe_patches("stress-fail", "repair", [failing], failing_record)
        out["failed_apply_count"] = len(applied_fail)
        out["failed_rollback_manifest_count"] = len(rollback_fail)
        out["failing_route"] = route_fail
        out["failed_patch_seen"] = any(e.get("event") == "patch_apply_failed" for e in failing_record.trace)
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

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
