from __future__ import annotations

import pytest

from the_daddy.git_tools import GitBranchExecutor


def test_refresh_base_branch_raises_when_ff_only_pull_fails(tmp_path, monkeypatch):
    executor = GitBranchExecutor(repo_root=tmp_path)

    monkeypatch.setattr(executor, "branch_exists_local", lambda _branch: True)
    monkeypatch.setattr(executor, "branch_exists_remote", lambda _branch: True)
    monkeypatch.setattr(executor, "_run_no_check", lambda *args: "")

    calls: list[tuple[str, ...]] = []

    def fake_run(*args: str) -> str:
        calls.append(args)
        if args == ("pull", "--ff-only", "origin", "main"):
            raise RuntimeError("git pull --ff-only failed")
        return ""

    monkeypatch.setattr(executor, "_run", fake_run)

    with pytest.raises(RuntimeError, match="ff-only"):
        executor.refresh_base_branch("main")

    assert ("pull", "--ff-only", "origin", "main") in calls


def test_refresh_base_branch_raises_and_stops_when_fetch_fails(tmp_path, monkeypatch):
    executor = GitBranchExecutor(repo_root=tmp_path)
    calls: list[tuple[str, ...]] = []

    def fake_run(*args: str) -> str:
        calls.append(args)
        if args == ("fetch", "origin", "main"):
            raise RuntimeError("git fetch failed")
        return ""

    monkeypatch.setattr(executor, "_run", fake_run)
    monkeypatch.setattr(executor, "branch_exists_local", lambda _branch: (_ for _ in ()).throw(AssertionError("branch_exists_local should not be called after fetch failure")))

    with pytest.raises(RuntimeError, match="fetch"):
        executor.refresh_base_branch("main")

    assert calls == [("fetch", "origin", "main")]
