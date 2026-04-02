from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional


class GitBranchExecutor:
    def __init__(self, repo_root: Path, github_token: str = "", github_repo: str = "") -> None:
        self.repo_root = repo_root
        self.github_token = github_token
        self.github_repo = github_repo

    def _run(self, cmd: List[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )

    def _is_git_repo(self) -> bool:
        result = self._run(["git", "rev-parse", "--is-inside-work-tree"])
        return result.returncode == 0 and result.stdout.strip() == "true"

    def _safe_branch_name(self, run_id: str) -> str:
        return f"daddy/{run_id}"

    def prepare_branch(self, run_id: str) -> str:
        if not self._is_git_repo():
            raise RuntimeError("Not a git repository")

        branch = self._safe_branch_name(run_id)

        # Always fetch latest
        self._run(["git", "fetch", "origin"])

        # Checkout main safely (no hard reset to avoid data loss locally)
        self._run(["git", "checkout", "main"])
        self._run(["git", "pull", "origin", "main"])

        # Create new branch from updated main
        self._run(["git", "checkout", "-b", branch])

        return branch

    def commit_current_branch_changes(self, run_id: str, changed_files: List[str]) -> Optional[str]:
        if not changed_files:
            return None

        # Add only known changed files
        for path in changed_files:
            self._run(["git", "add", path])

        # Check if anything is staged
        diff = self._run(["git", "diff", "--cached", "--name-only"])
        if not diff.stdout.strip():
            return None

        commit_message = f"auto: daddy patch {run_id}"
        self._run(["git", "commit", "-m", commit_message])

        # Get current branch
        branch_result = self._run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        branch = branch_result.stdout.strip()

        # Push branch
        self._run(["git", "push", "-u", "origin", branch])

        return branch

    def create_pull_request(
        self,
        *,
        branch_name: str,
        title: str,
        body: str,
        base_branch: str = "main",
    ) -> Optional[dict]:
        if not self.github_token or not self.github_repo:
            return None

        import requests

        url = f"https://api.github.com/repos/{self.github_repo}/pulls"
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github+json",
        }

        payload = {
            "title": title,
            "head": branch_name,
            "base": base_branch,
            "body": body,
        }

        response = requests.post(url, json=payload, headers=headers)

        if response.status_code not in (200, 201):
            return None

        return response.json()

    def merge_pull_request(self, pull_number: int, commit_title: str) -> Optional[dict]:
        if not self.github_token or not self.github_repo:
            return None

        import requests

        url = f"https://api.github.com/repos/{self.github_repo}/pulls/{pull_number}/merge"
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github+json",
        }

        payload = {
            "commit_title": commit_title,
            "merge_method": "squash",
        }

        response = requests.put(url, json=payload, headers=headers)

        if response.status_code not in (200, 201):
            return None

        return response.json()
