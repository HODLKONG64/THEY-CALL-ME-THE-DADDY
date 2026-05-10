
from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable


class GitBranchExecutor:
    def __init__(self, repo_root: Path | str = ".", github_token: str = "", github_repo: str = "") -> None:
        self.repo_root = Path(repo_root).resolve()
        self.github_token = github_token
        self.github_repo = github_repo

    def _run(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed with code {result.returncode}\n"
                f"STDOUT:\n{result.stdout.strip()}\n\nSTDERR:\n{result.stderr.strip()}"
            )
        return result.stdout.strip()

    def _run_no_check(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )

    def _repo_owner(self) -> str:
        if "/" not in self.github_repo:
            raise RuntimeError(f"Invalid github_repo value: {self.github_repo!r}")
        return self.github_repo.split("/", 1)[0]

    def _api_request(self, method: str, url: str, payload: dict | None = None) -> dict | list:
        if not self.github_token or not self.github_repo:
            raise RuntimeError("GitHub API not configured")

        data = None
        headers = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "daddy-agent",
        }

        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=data, method=method, headers=headers)

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            try:
                parsed = json.loads(body) if body else {}
            except Exception:
                parsed = {"raw_body": body}
            raise RuntimeError(
                f"GitHub API {method} {url} failed with HTTP {exc.code}: {parsed}"
            ) from exc

    def current_branch(self) -> str:
        return self._run("rev-parse", "--abbrev-ref", "HEAD")

    def branch_exists_local(self, branch_name: str) -> bool:
        result = self._run_no_check("show-ref", "--verify", f"refs/heads/{branch_name}")
        return result.returncode == 0

    def branch_exists_remote(self, branch_name: str) -> bool:
        result = self._run_no_check("ls-remote", "--heads", "origin", branch_name)
        return result.returncode == 0 and bool(result.stdout.strip())

    def refresh_base_branch(self, base_branch: str = "main") -> None:
        self._run_no_check("fetch", "origin", base_branch)

        if self.branch_exists_local(base_branch):
            self._run("checkout", base_branch)
            if self.branch_exists_remote(base_branch):
                self._run_no_check("pull", "--ff-only", "origin", base_branch)
        else:
            if self.branch_exists_remote(base_branch):
                self._run("checkout", "-B", base_branch, f"origin/{base_branch}")
            else:
                self._run("checkout", "-B", base_branch)

    def create_or_checkout_branch(self, branch_name: str, base_branch: str = "main") -> str:
        self.refresh_base_branch(base_branch)
        if self.branch_exists_local(branch_name):
            self._run("checkout", branch_name)
        else:
            self._run("checkout", "-b", branch_name)
        return self.current_branch()

    def prepare_branch(self, run_id: str, base_branch: str = "main") -> str:
        branch_name = self.branch_for_architecture_run(run_id)
        return self.create_or_checkout_branch(branch_name, base_branch=base_branch)

    def add_safe_paths(self, paths: Iterable[str]) -> None:
        path_list = [str(path) for path in paths if str(path).strip()]
        if path_list:
            self._run("add", *path_list)

    def has_staged_changes(self) -> bool:
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode != 0

    def has_working_tree_changes(self, paths: Iterable[str] | None = None) -> bool:
        cmd = ["git", "diff", "--quiet"]
        if paths:
            cmd.append("--")
            cmd.extend([str(path) for path in paths if str(path).strip()])
        result = subprocess.run(
            cmd,
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
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

    def _verify_py_files(self, paths: Iterable[str]) -> None:
        for path in paths:
            if not str(path).endswith(".py"):
                continue
            full = self.repo_root / path
            if not full.exists():
                raise FileNotFoundError(f"Pre-push syntax check: file not found: {path}")
            result = subprocess.run(
                ["python", "-m", "py_compile", str(full)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise ValueError(
                    f"Pre-push syntax check failed for {path}:\n{result.stderr.strip()}"
                )

    def commit_current_branch_changes(self, run_id: str, safe_paths: Iterable[str]) -> str | None:
        paths = [str(path) for path in safe_paths if str(path).strip()]
        if not paths:
            return None

        branch_name = self.current_branch()

        if not self.has_working_tree_changes(paths) and not self.has_staged_changes():
            return None

        self.add_safe_paths(paths)
        committed = self.commit(f"auto: daddy architecture plan {run_id}")
        if not committed:
            return None

        self._verify_py_files(paths)
        self.push(branch_name)

        return branch_name

    def _find_existing_open_pr(self, branch_name: str, base_branch: str = "main") -> dict | None:
        owner = self._repo_owner()
        params = urllib.parse.urlencode(
            {"state": "open", "head": f"{owner}:{branch_name}", "base": base_branch}
        )
        url = f"https://api.github.com/repos/{self.github_repo}/pulls?{params}"
        response = self._api_request("GET", url)
        if isinstance(response, list) and response:
            return response[0]
        return None

    def create_pull_request(self, branch_name: str, title: str, body: str, base_branch: str = "main") -> dict | None:
        if not self.github_token or not self.github_repo:
            return None

        url = f"https://api.github.com/repos/{self.github_repo}/pulls"
        payload = {
            "title": title,
            "head": branch_name,
            "base": base_branch,
            "body": body,
            "draft": False,
        }

        try:
            response = self._api_request("POST", url, payload)
            if isinstance(response, dict):
                return response
            raise RuntimeError(f"Unexpected PR creation response: {response}")
        except RuntimeError as exc:
            text = str(exc)
            if "A pull request already exists" in text or "already exists" in text:
                existing = self._find_existing_open_pr(branch_name, base_branch)
                if existing is not None:
                    return existing
            raise

    def merge_pull_request(self, pull_number: int, commit_title: str = "auto: daddy merge") -> dict | None:
        if not self.github_token or not self.github_repo:
            return None
        url = f"https://api.github.com/repos/{self.github_repo}/pulls/{pull_number}/merge"
        payload = {"commit_title": commit_title, "merge_method": "squash"}
        response = self._api_request("PUT", url, payload)
        if isinstance(response, dict):
            return response
        raise RuntimeError(f"Unexpected PR merge response: {response}")
