from __future__ import annotations

from pathlib import Path

from the_daddy.config import DADDY_REPO, SWARMSY_REPO, Settings
from the_daddy.engine import DaddyEngine, make_run_id
from the_daddy.models import ArchitectureReview, RunRecord


def _settings(tmp_path: Path) -> Settings:
    s = Settings()
    s.target_root = tmp_path
    s.local_state_dir = tmp_path / "local_state"
    s.memory_file_name = "test-memory.json"
    s.command = "python -c \"print('ok')\""
    s.github_token = "token"
    s.github_repo = DADDY_REPO
    s.swarmsy_auto_merge = False
    return s


def _record() -> RunRecord:
    return RunRecord(
        run_id=make_run_id(),
        command="pytest -q",
        success=True,
        selected_mode="architecture",
        patches_applied=[{"path": "src/the_daddy/runtime/trace_summary.py", "bytes_before": 1, "bytes_after": 2}],
        architecture_review=ArchitectureReview(
            diagnosis="ok",
            system_intent="ok",
            strengths=[],
            weaknesses=[],
            recommendations=[],
            backlog_items=[],
            self_evolution_actions=[],
            build_actions=[],
            architecture_plans=[],
            execution_notes=[],
            risk_level="low",
        ),
    )


class _GitStub:
    def __init__(self) -> None:
        self.merges: list[int] = []

    def commit_current_branch_changes(self, _run_id: str, _safe_paths: list[str]) -> str:
        return "daddy-architecture-test"

    def create_pull_request(self, **_kwargs):
        return {"number": 7, "html_url": "https://example.test/pull/7"}

    def merge_pull_request(self, pull_number: int, commit_title: str = ""):
        self.merges.append(pull_number)
        return {"merged": True, "title": commit_title}


def test_self_repair_auto_merge_path_still_works(tmp_path: Path):
    engine = DaddyEngine(_settings(tmp_path))
    git = _GitStub()
    engine.git_tools = git
    engine.merge_judge.should_auto_merge = lambda **_kwargs: (True, [])

    record = _record()
    engine._deliver_patch_via_pr(record, "safe", prepared_branch="daddy-architecture-test")

    assert git.merges == [7]
    assert any(event.get("event") == "pr_merged" for event in record.trace)


def test_swarmsy_mode_defaults_to_pr_only_without_auto_merge(tmp_path: Path):
    settings = _settings(tmp_path)
    settings.github_repo = SWARMSY_REPO
    settings.swarmsy_auto_merge = False
    engine = DaddyEngine(settings)
    git = _GitStub()
    engine.git_tools = git
    engine.merge_judge.should_auto_merge = lambda **_kwargs: (True, [])

    record = _record()
    engine._deliver_patch_via_pr(record, "safe", prepared_branch="daddy-architecture-test")

    assert git.merges == []
    merge_judgement = next(event for event in record.trace if event.get("event") == "merge_judgement")
    assert merge_judgement.get("allowed") is False
    assert any("SWARMSY auto-merge disabled by default" in reason for reason in merge_judgement.get("reasons", []))
    assert any(event.get("event") == "pr_left_open" for event in record.trace)
