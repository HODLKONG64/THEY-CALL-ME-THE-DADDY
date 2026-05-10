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
    monkeypatch.setattr(executor, "branch_exists_remote", lambda _branch: True)
    monkeypatch.setattr(executor, "branch_exists_local", lambda _branch: (_ for _ in ()).throw(AssertionError("branch_exists_local should not be called after fetch failure")))

    with pytest.raises(RuntimeError, match="fetch"):
        executor.refresh_base_branch("main")

    assert calls == [("fetch", "origin", "main")]


def test_refresh_base_branch_raises_when_remote_base_branch_missing(tmp_path, monkeypatch):
    executor = GitBranchExecutor(repo_root=tmp_path)
    calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(executor, "branch_exists_remote", lambda _branch: False)
    monkeypatch.setattr(executor, "_run", lambda *args: calls.append(args) or "")

    with pytest.raises(RuntimeError, match="Remote base branch does not exist"):
        executor.refresh_base_branch("main")

    assert calls == []


def test_create_or_checkout_branch_aligns_with_remote_when_remote_branch_exists(tmp_path, monkeypatch):
    executor = GitBranchExecutor(repo_root=tmp_path)
    calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(executor, "refresh_base_branch", lambda _base: calls.append(("refresh", _base)))
    monkeypatch.setattr(executor, "branch_exists_remote", lambda branch: branch == "feature")
    monkeypatch.setattr(executor, "branch_exists_local", lambda _branch: True)
    monkeypatch.setattr(executor, "current_branch", lambda: "feature")
    monkeypatch.setattr(executor, "_run", lambda *args: calls.append(args) or "")

    out = executor.create_or_checkout_branch("feature", base_branch="main")

    assert out == "feature"
    assert ("fetch", "origin", "feature") in calls
    assert ("checkout", "-B", "feature", "origin/feature") in calls


def test_commit_current_branch_changes_raises_when_push_rejected(tmp_path, monkeypatch):
    executor = GitBranchExecutor(repo_root=tmp_path)

    monkeypatch.setattr(executor, "has_working_tree_changes", lambda _paths: True)
    monkeypatch.setattr(executor, "has_staged_changes", lambda: True)
    monkeypatch.setattr(executor, "current_branch", lambda: "feature")
    monkeypatch.setattr(executor, "add_safe_paths", lambda _paths: None)
    monkeypatch.setattr(executor, "commit", lambda _message: True)
    monkeypatch.setattr(executor, "_verify_py_files", lambda _paths: None)
    monkeypatch.setattr(executor, "push", lambda _branch: (_ for _ in ()).throw(RuntimeError("non-fast-forward push rejected")))

    with pytest.raises(RuntimeError, match="non-fast-forward"):
        executor.commit_current_branch_changes("rid", ["src/the_daddy/runtime/trace_summary.py"])
