from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
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

    def _github_request(self, method: str, url: str, payload: dict | None = None) -> Optional[dict]:
        if not self.github_token or not self.github_repo:
            return None

        data = None
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "the-daddy-agent",
        }

        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            url=url,
            data=data,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                if not raw.strip():
                    return {}
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
        except urllib.error.HTTPError:
            return None
        except urllib.error.URLError:
            return None
        except Exception:
            return None

    def prepare_branch(self, run_id: str) -> str:
        if not self._is_git_repo():
            raise RuntimeError("Not a git repository")

        branch = self._safe_branch_name(run_id)

        self._run(["git", "fetch", "origin"])
        self._run(["git", "checkout", "main"])
        self._run(["git", "pull", "origin", "main"])

        exists = self._run(["git", "rev-parse", "--verify", branch])
        if exists.returncode == 0:
            self._run(["git", "checkout", branch])
            self._run(["git", "reset", "--soft", "main"])
        else:
            self._run(["git", "checkout", "-b", branch])

        return branch

    def commit_current_branch_changes(self, run_id: str, changed_files: List[str]) -> Optional[str]:
        if not changed_files:
            return None

        for path in changed_files:
            self._run(["git", "add", path])

        diff = self._run(["git", "diff", "--cached", "--name-only"])
        if not diff.stdout.strip():
            return None

        commit_message = f"auto: daddy patch {run_id}"
        commit = self._run(["git", "commit", "-m", commit_message])
        if commit.returncode != 0:
            return None

        branch_result = self._run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        branch = branch_result.stdout.strip()
        if not branch:
            return None

        push = self._run(["git", "push", "-u", "origin", branch])
        if push.returncode != 0:
            return None

        return branch

    def create_pull_request(
        self,
        *,
        branch_name: str,
        title: str,
        body: str,
        base_branch: str = "main",
    ) -> Optional[dict]:
        url = f"https://api.github.com/repos/{self.github_repo}/pulls"
        payload = {
            "title": title,
            "head": branch_name,
            "base": base_branch,
            "body": body,
        }
        return self._github_request("POST", url, payload)

    def merge_pull_request(self, pull_number: int, commit_title: str) -> Optional[dict]:
        url = f"https://api.github.com/repos/{self.github_repo}/pulls/{pull_number}/merge"
        payload = {
            "commit_title": commit_title,
            "merge_method": "squash",
        }
        return self._github_request("PUT", url, payload)
