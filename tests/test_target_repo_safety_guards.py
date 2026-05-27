"""Tests for target-repo safety guards (rescued from PR #90 after SWARMSY queue merge).

Covers:
- config: DADDY_ALLOWED_TARGET_REPOS / DADDY_SWARMSY_AUTO_MERGE parsing
- git_tools: _ensure_target_repo_allowed blocks push / create_pr / merge_pr
- Daddy self-repair default path still works
- SWARMSY external mode requires explicit allowlist entry
- Docs identity check
"""
from __future__ import annotations

import pathlib

import pytest

from the_daddy.config import Settings, _parse_allowed_target_repos
from the_daddy.engine import DaddyEngine, make_run_id
from the_daddy.git_tools import GitBranchExecutor, _DEFAULT_ALLOWED_TARGET_REPOS
from the_daddy.models import RunRecord

DADDY_REPO = "HODLKONG64/THEY-CALL-ME-THE-DADDY"
SWARMSY_REPO = "HODLKONG64/SWARMSY"
EXTERNAL_REPO = "acme/private-repo"
DADDY_REPO_NORM = DADDY_REPO.lower()
SWARMSY_REPO_NORM = SWARMSY_REPO.lower()


# ---------------------------------------------------------------------------
# Config: _parse_allowed_target_repos
# ---------------------------------------------------------------------------


def test_parse_allowed_target_repos_empty_string_fails_closed_to_daddy():
    repos = _parse_allowed_target_repos("")
    assert repos == frozenset({DADDY_REPO_NORM})


def test_parse_allowed_target_repos_single_entry():
    repos = _parse_allowed_target_repos(DADDY_REPO)
    assert DADDY_REPO_NORM in repos


def test_parse_allowed_target_repos_comma_separated():
    repos = _parse_allowed_target_repos(f"{DADDY_REPO},{SWARMSY_REPO}")
    assert DADDY_REPO_NORM in repos
    assert SWARMSY_REPO_NORM in repos


def test_parse_allowed_target_repos_whitespace_stripped():
    repos = _parse_allowed_target_repos(f"  {DADDY_REPO} , {SWARMSY_REPO}  ")
    assert DADDY_REPO_NORM in repos
    assert SWARMSY_REPO_NORM in repos


def test_parse_allowed_target_repos_ignores_empty_items():
    repos = _parse_allowed_target_repos(f"{DADDY_REPO},,{SWARMSY_REPO},")
    assert DADDY_REPO_NORM in repos
    assert SWARMSY_REPO_NORM in repos
    assert "" not in repos


# ---------------------------------------------------------------------------
# Config: Settings fields
# ---------------------------------------------------------------------------


def test_settings_default_allowed_target_repos_contains_daddy(monkeypatch):
    monkeypatch.delenv("DADDY_ALLOWED_TARGET_REPOS", raising=False)
    settings = Settings()
    assert DADDY_REPO_NORM in settings.allowed_target_repos


def test_settings_default_allowed_target_repos_fails_closed(monkeypatch):
    monkeypatch.delenv("DADDY_ALLOWED_TARGET_REPOS", raising=False)
    settings = Settings()
    assert settings.allowed_target_repos == frozenset({DADDY_REPO_NORM})


def test_settings_swarmsy_auto_merge_defaults_false(monkeypatch):
    monkeypatch.delenv("DADDY_SWARMSY_AUTO_MERGE", raising=False)
    settings = Settings()
    assert settings.swarmsy_auto_merge is False


def test_settings_swarmsy_auto_merge_enabled_by_env(monkeypatch):
    monkeypatch.setenv("DADDY_SWARMSY_AUTO_MERGE", "true")
    settings = Settings()
    assert settings.swarmsy_auto_merge is True


def test_settings_allowed_repos_read_from_env(monkeypatch):
    monkeypatch.setenv("DADDY_ALLOWED_TARGET_REPOS", f"{DADDY_REPO},{SWARMSY_REPO}")
    settings = Settings()
    assert DADDY_REPO_NORM in settings.allowed_target_repos
    assert SWARMSY_REPO_NORM in settings.allowed_target_repos


# ---------------------------------------------------------------------------
# GitBranchExecutor: default allowlist
# ---------------------------------------------------------------------------


def test_default_allowed_target_repos_constant_contains_daddy():
    assert DADDY_REPO in _DEFAULT_ALLOWED_TARGET_REPOS


def test_executor_default_allowlist_contains_daddy(tmp_path):
    executor = GitBranchExecutor(repo_root=tmp_path)
    assert DADDY_REPO in executor.allowed_target_repos


def test_executor_default_allowlist_does_not_contain_swarmsy(tmp_path):
    executor = GitBranchExecutor(repo_root=tmp_path)
    assert SWARMSY_REPO not in executor.allowed_target_repos


# ---------------------------------------------------------------------------
# GitBranchExecutor: _ensure_target_repo_allowed
# ---------------------------------------------------------------------------


def test_guard_passes_for_daddy_repo(tmp_path):
    executor = GitBranchExecutor(repo_root=tmp_path, github_token="t", github_repo=DADDY_REPO)
    executor._ensure_target_repo_allowed("push")  # must not raise


def test_guard_blocks_disallowed_repo(tmp_path):
    executor = GitBranchExecutor(repo_root=tmp_path, github_token="t", github_repo=EXTERNAL_REPO)
    with pytest.raises(PermissionError, match="not in the allowed target repos allowlist"):
        executor._ensure_target_repo_allowed("push")


def test_push_blocks_when_github_repo_is_empty(tmp_path, monkeypatch):
    executor = GitBranchExecutor(repo_root=tmp_path, github_token="t", github_repo="")
    run_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(executor, "_run", lambda *args: run_calls.append(args))
    with pytest.raises(PermissionError, match="GITHUB_REPO is unset"):
        executor.push("some-branch")
    assert run_calls == [], "git push subprocess must never be reached when github_repo is empty"


def test_guard_normalizes_case_and_whitespace_in_github_repo_and_allowlist(tmp_path):
    executor = GitBranchExecutor(
        repo_root=tmp_path,
        github_token="t",
        github_repo="  HODLKONG64/They-Call-Me-The-Daddy ",
        allowed_target_repos=frozenset({"hodlkong64/they-call-me-the-daddy"}),
    )
    executor._ensure_target_repo_allowed("push")


def test_guard_normalized_mixed_case_allowlist_matches_lowercase_repo(tmp_path):
    executor = GitBranchExecutor(
        repo_root=tmp_path,
        github_token="t",
        github_repo="hodlkong64/they-call-me-the-daddy",
        allowed_target_repos=frozenset({"  HODLKONG64/THEY-CALL-ME-THE-DADDY "}),
    )
    executor._ensure_target_repo_allowed("create_pull_request")


def test_guard_passes_for_swarmsy_when_explicitly_allowlisted(tmp_path):
    executor = GitBranchExecutor(
        repo_root=tmp_path,
        github_token="t",
        github_repo=SWARMSY_REPO,
        allowed_target_repos=frozenset({DADDY_REPO, SWARMSY_REPO}),
    )
    executor._ensure_target_repo_allowed("push")  # must not raise


def test_guard_blocks_swarmsy_when_not_in_allowlist(tmp_path):
    executor = GitBranchExecutor(
        repo_root=tmp_path,
        github_token="t",
        github_repo=SWARMSY_REPO,
        # default allowlist = Daddy only
    )
    with pytest.raises(PermissionError):
        executor._ensure_target_repo_allowed("create_pull_request")


# ---------------------------------------------------------------------------
# push() is blocked before git subprocess is called
# ---------------------------------------------------------------------------


def test_push_blocked_for_disallowed_repo_before_git_subprocess(tmp_path, monkeypatch):
    executor = GitBranchExecutor(repo_root=tmp_path, github_token="t", github_repo=EXTERNAL_REPO)
    run_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(executor, "_run", lambda *args: run_calls.append(args))

    with pytest.raises(PermissionError):
        executor.push("some-branch")

    assert run_calls == [], "git push subprocess must never be reached for disallowed repo"


def test_push_allowed_for_daddy_repo(tmp_path, monkeypatch):
    executor = GitBranchExecutor(repo_root=tmp_path, github_token="t", github_repo=DADDY_REPO)
    monkeypatch.setattr(executor, "_run", lambda *_args: "")
    executor.push("daddy-branch")  # must not raise


# ---------------------------------------------------------------------------
# create_pull_request() is blocked before any remote call
# ---------------------------------------------------------------------------


def test_create_pr_blocked_for_disallowed_repo_before_api_call(tmp_path, monkeypatch):
    executor = GitBranchExecutor(repo_root=tmp_path, github_token="t", github_repo=EXTERNAL_REPO)
    api_calls: list = []
    monkeypatch.setattr(executor, "_api_request", lambda *a, **kw: api_calls.append(a))

    with pytest.raises(PermissionError):
        executor.create_pull_request("branch", "title", "body")

    assert api_calls == [], "no remote API call must be attempted for disallowed repo"


def test_create_pr_blocks_when_github_repo_is_empty(tmp_path):
    executor = GitBranchExecutor(repo_root=tmp_path, github_token="t", github_repo="")
    with pytest.raises(PermissionError, match="GITHUB_REPO is unset"):
        executor.create_pull_request("branch", "title", "body")


# ---------------------------------------------------------------------------
# merge_pull_request() is blocked before any remote call
# ---------------------------------------------------------------------------


def test_merge_pr_blocked_for_disallowed_repo_before_api_call(tmp_path, monkeypatch):
    executor = GitBranchExecutor(repo_root=tmp_path, github_token="t", github_repo=EXTERNAL_REPO)
    api_calls: list = []
    monkeypatch.setattr(executor, "_api_request", lambda *a, **kw: api_calls.append(a))

    with pytest.raises(PermissionError):
        executor.merge_pull_request(42)

    assert api_calls == [], "no remote API call must be attempted for disallowed repo"


def test_merge_pr_blocks_when_github_repo_is_empty(tmp_path):
    executor = GitBranchExecutor(repo_root=tmp_path, github_token="t", github_repo="")
    with pytest.raises(PermissionError, match="GITHUB_REPO is unset"):
        executor.merge_pull_request(1)


# ---------------------------------------------------------------------------
# Daddy self-repair auto-merge path not broken
# ---------------------------------------------------------------------------


def test_daddy_self_repair_merge_pr_succeeds(tmp_path, monkeypatch):
    """merge_pull_request must work end-to-end for the Daddy self-repair repo."""
    executor = GitBranchExecutor(repo_root=tmp_path, github_token="t", github_repo=DADDY_REPO)
    monkeypatch.setattr(
        executor,
        "_api_request",
        lambda *_a, **_kw: {"merged": True, "message": "Pull Request successfully merged"},
    )
    result = executor.merge_pull_request(99)
    assert result is not None
    assert result.get("merged") is True


def test_daddy_self_repair_create_pr_succeeds(tmp_path, monkeypatch):
    """create_pull_request must work end-to-end for the Daddy self-repair repo."""
    executor = GitBranchExecutor(repo_root=tmp_path, github_token="t", github_repo=DADDY_REPO)
    monkeypatch.setattr(
        executor,
        "_api_request",
        lambda *_a, **_kw: {"number": 7, "html_url": f"https://github.com/{DADDY_REPO}/pull/7"},
    )
    result = executor.create_pull_request("daddy-branch", "fix: test", "body text")
    assert result is not None
    assert result.get("number") == 7


# ---------------------------------------------------------------------------
# DaddyEngine: SWARMSY auto-merge gating
# ---------------------------------------------------------------------------


def _make_engine_with_repo(tmp_path, repo: str, *, swarmsy_auto_merge: bool) -> DaddyEngine:
    settings = Settings(
        target_root=tmp_path,
        command="python -c \"print('ok')\"",
        github_token="t",
        github_repo=repo,
        swarmsy_auto_merge=swarmsy_auto_merge,
        enable_self_evolution=False,
        enable_architecture_lane=False,
    )
    return DaddyEngine(settings)


def _record_for_pr_delivery() -> RunRecord:
    record = RunRecord(run_id=make_run_id(), command="pytest -q")
    record.success = True
    record.patches_applied = [{"path": "src/the_daddy/git_tools.py", "bytes_before": 10, "bytes_after": 20}]
    return record


class _FakeGitTools:
    def __init__(self) -> None:
        self.merge_calls: list[dict] = []

    def prepare_branch(self, run_id):
        return "test-branch"

    def commit_current_branch_changes(self, run_id, files):
        return "test-branch"

    def create_pull_request(self, **kwargs):
        return {"number": 123, "html_url": "https://example.test/pr/123"}

    def merge_pull_request(self, **kwargs):
        self.merge_calls.append(kwargs)
        return {"merged": True}


def test_daddy_repo_auto_merge_path_still_allowed(tmp_path):
    engine = _make_engine_with_repo(tmp_path, DADDY_REPO, swarmsy_auto_merge=False)
    fake_git = _FakeGitTools()
    engine.git_tools = fake_git
    engine.merge_judge.should_auto_merge = lambda **_kwargs: (True, ["allowed_for_test"])

    record = _record_for_pr_delivery()
    engine._deliver_patch_via_pr(record, "safe")

    assert len(fake_git.merge_calls) == 1


def test_swarmsy_repo_auto_merge_disabled_leaves_pr_open(tmp_path):
    engine = _make_engine_with_repo(tmp_path, SWARMSY_REPO, swarmsy_auto_merge=False)
    fake_git = _FakeGitTools()
    engine.git_tools = fake_git
    engine.merge_judge.should_auto_merge = lambda **_kwargs: (True, ["allowed_for_test"])

    record = _record_for_pr_delivery()
    engine._deliver_patch_via_pr(record, "safe")

    assert fake_git.merge_calls == []
    assert any(
        event.get("event") == "pr_left_open"
        and "swarmsy_auto_merge_disabled" in (event.get("reasons") or [])
        for event in record.trace
    )


def test_swarmsy_repo_auto_merge_enabled_can_merge_when_normal_gates_allow(tmp_path):
    engine = _make_engine_with_repo(tmp_path, SWARMSY_REPO, swarmsy_auto_merge=True)
    fake_git = _FakeGitTools()
    engine.git_tools = fake_git
    engine.merge_judge.should_auto_merge = lambda **_kwargs: (True, ["allowed_for_test"])

    record = _record_for_pr_delivery()
    engine._deliver_patch_via_pr(record, "safe")

    assert len(fake_git.merge_calls) == 1


# ---------------------------------------------------------------------------
# Docs identity check
# ---------------------------------------------------------------------------


def test_readme_does_not_claim_daddy_is_swarmsy_app_runtime():
    """The README must not claim THEY-CALL-ME-THE-DADDY IS the SWARMSY app runtime."""
    readme_path = pathlib.Path(__file__).parent.parent / "README.md"
    text = readme_path.read_text(encoding="utf-8").lower()
    assert "daddy is the swarmsy app runtime" not in text
    assert "daddy is the swarmsy runtime" not in text


def test_readme_safety_section_references_no_middleman_doc():
    """The README safety section must reference the no-middleman queue doc."""
    readme_path = pathlib.Path(__file__).parent.parent / "README.md"
    text = readme_path.read_text(encoding="utf-8")
    assert "SWARMSY_DOCTOR_NO_MIDDLEMAN.md" in text


def test_readme_safety_section_describes_allowlist():
    """The README must mention DADDY_ALLOWED_TARGET_REPOS."""
    readme_path = pathlib.Path(__file__).parent.parent / "README.md"
    text = readme_path.read_text(encoding="utf-8")
    assert "DADDY_ALLOWED_TARGET_REPOS" in text


def test_readme_safety_section_describes_auto_merge_default():
    """The README must mention DADDY_SWARMSY_AUTO_MERGE."""
    readme_path = pathlib.Path(__file__).parent.parent / "README.md"
    text = readme_path.read_text(encoding="utf-8")
    assert "DADDY_SWARMSY_AUTO_MERGE" in text
