from __future__ import annotations

import json
import subprocess
import urllib.request
from pathlib import Path
from typing import Iterable


class GitBranchExecutor:
    def __init__(self, repo_root: Path | str = ".", github_token: str = "", github_repo: str = "") -> None:
        self.repo_root = Path(repo_root).resolve()
        self.github_token = github_token
        self.github_repo = github_repo  # owner/repo

    def _run(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def current_branch(self) -> str:
        return self._run("rev-parse", "--abbrev-ref", "HEAD")

    def head_sha(self) -> str:
        return self._run("rev-parse", "HEAD")

    def create_or_checkout_branch(self, branch_name: str, base_branch: str = "main") -> str:
        try:
            self._run("checkout", branch_name)
        except Exception:
            self._run("checkout", base_branch)
            self._run("checkout", "-b", branch_name)
        return self.current_branch()

    def add_safe_paths(self, paths: Iterable[str]) -> None:
        for path in paths:
            try:
                self._run("add", path)
            except Exception:
                continue

    def has_staged_changes(self) -> bool:
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        return result.returncode != 0

    def commit(self, message: str) -> bool:
        if not self.has_staged_changes():
            return False
        self._run("config", "user.name", "github-actions")
        self._run("config", "user.email", "github-actions@github.com")
        self._run("commit", "-m", message)
        return True

    def push(self, branch_name: str) -> None:
        self._run("push", "-u", "origin", branch_name)

    def branch_for_architecture_run(self, run_id: str) -> str:
        return f"daddy-architecture-{run_id.lower()}"

    def commit_safe_branch_changes(self, run_id: str, safe_paths: Iterable[str]) -> str | None:
        branch_name = self.branch_for_architecture_run(run_id)
        self.create_or_checkout_branch(branch_name)
        self.add_safe_paths(safe_paths)
        committed = self.commit(f"auto: daddy architecture plan {run_id}")
        if not committed:
            return None
        self.push(branch_name)
        return branch_name

    def create_pull_request(
        self,
        branch_name: str,
        title: str,
        body: str,
        base_branch: str = "main",
    ) -> dict | None:
        if not self.github_token or not self.github_repo:
            return None

        url = f"https://api.github.com/repos/{self.github_repo}/pulls"
        payload = json.dumps(
            {
                "title": title,
                "head": branch_name,
                "base": base_branch,
                "body": body,
                "draft": False,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.github_token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "daddy-agent",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            return None

    def merge_pull_request(self, pull_number: int, commit_title: str = "auto: daddy merge") -> dict | None:
        if not self.github_token or not self.github_repo:
            return None

        url = f"https://api.github.com/repos/{self.github_repo}/pulls/{pull_number}/merge"
        payload = json.dumps(
            {
                "commit_title": commit_title,
                "merge_method": "squash",
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=payload,
            method="PUT",
            headers={
                "Authorization": f"Bearer {self.github_token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "daddy-agent",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            return None

    def commit_push_open_pr(
        self,
        run_id: str,
        safe_paths: Iterable[str],
        title: str,
        body: str,
        base_branch: str = "main",
    ) -> dict | None:
        branch_name = self.commit_safe_branch_changes(run_id, safe_paths)
        if not branch_name:
            return None
        return self.create_pull_request(
            branch_name=branch_name,
            title=title,
            body=body,
            base_branch=base_branch,
        )
