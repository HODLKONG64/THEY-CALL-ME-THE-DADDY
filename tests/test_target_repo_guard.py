from __future__ import annotations

from pathlib import Path

import pytest

from the_daddy.config import Settings
from the_daddy.git_tools import GitBranchExecutor


def test_default_allowed_target_repo_is_daddy_only(monkeypatch):
    monkeypatch.delenv("DADDY_ALLOWED_TARGET_REPOS", raising=False)

    settings = Settings()

    assert settings.allowed_target_repos == ["HODLKONG64/THEY-CALL-ME-THE-DADDY"]


def test_disallowed_github_repo_blocks_pr_creation(tmp_path: Path, monkeypatch):
    executor = GitBranchExecutor(
        repo_root=tmp_path,
        github_token="token",
        github_repo="HODLKONG64/SWARMSY",
    )

    monkeypatch.setattr(
        executor,
        "_api_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("API should not be called")),
    )

    with pytest.raises(RuntimeError, match="not allowlisted"):
        executor.create_pull_request("branch", "title", "body")


def test_disallowed_github_repo_blocks_pr_merge(tmp_path: Path, monkeypatch):
    executor = GitBranchExecutor(
        repo_root=tmp_path,
        github_token="token",
        github_repo="HODLKONG64/SWARMSY",
    )

    monkeypatch.setattr(
        executor,
        "_api_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("API should not be called")),
    )

    with pytest.raises(RuntimeError, match="not allowlisted"):
        executor.merge_pull_request(7)


def test_allowlisted_swarmsy_target_is_accepted_when_explicitly_configured(tmp_path: Path, monkeypatch):
    executor = GitBranchExecutor(
        repo_root=tmp_path,
        github_token="token",
        github_repo="HODLKONG64/SWARMSY",
        allowed_target_repos=[
            "HODLKONG64/THEY-CALL-ME-THE-DADDY",
            "HODLKONG64/SWARMSY",
        ],
    )

    calls: list[tuple[str, str, dict]] = []

    def fake_api_request(method: str, url: str, payload: dict | None = None):
        calls.append((method, url, payload or {}))
        return {"number": 1, "html_url": "https://example.test/pull/1"}

    monkeypatch.setattr(executor, "_api_request", fake_api_request)

    result = executor.create_pull_request("branch", "title", "body")

    assert result == {"number": 1, "html_url": "https://example.test/pull/1"}
    assert calls[0][0] == "POST"
    assert calls[0][1].endswith("/repos/HODLKONG64/SWARMSY/pulls")
