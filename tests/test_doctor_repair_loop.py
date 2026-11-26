from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from the_daddy.config import Settings
from the_daddy.doctor_repair import DoctorWorkspace
from the_daddy.doctor_worker import CODEX_BOT, GitHubDoctorWorker
from the_daddy.swarmsy_doctor import DoctorEdit, DoctorRequest, JsonDoctorArchive
from the_daddy.swarmsy_doctor_queue import main

REPO = "HODLKONG64/THEY-CALL-ME-THE-DADDY"
BOT = {"type": "Bot", "login": CODEX_BOT}


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


@pytest.fixture
def local_repo(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q", "-b", "main")
    git(source, "config", "user.name", "Tester")
    git(source, "config", "user.email", "test@example.com")
    (source / "src").mkdir()
    (source / "src/example.py").write_text("answer = 0\n")
    (source / "tests").mkdir()
    (source / "tests/__init__.py").touch()
    (source / "tests/check.py").write_text(
        "from src.example import answer\nassert answer in (1, 2), 'answer is wrong'\n"
    )
    git(source, "add", ".")
    git(source, "commit", "-qm", "broken answer")
    return source


class GitHubStub:
    def __init__(self, repo):
        self.repo = repo
        self.branch = ""
        self.review_requests = []
        self.reviews = []
        self.annotations = {}
        self.reactions = {}
        self.ci_success = False
        self.merged = False
        self.merge_calls = []
        self.pr_creates = 0

    def head(self):
        return git(self.repo, "rev-parse", f"refs/heads/{self.branch}")

    def pr(self):
        return {
            "number": 1, "state": "closed" if self.merged else "open", "draft": False, "merged": self.merged,
            "mergeable": True, "mergeable_state": "clean",
            "head": {"repo": {"full_name": REPO}, "ref": self.branch, "sha": self.head()},
            "base": {"repo": {"full_name": REPO}, "ref": "main", "sha": git(self.repo, "rev-parse", "main")},
        }

    def create(self, branch, title, body, *, base_branch):
        assert base_branch == "main"
        self.branch = branch
        self.pr_creates += 1
        return self.pr()

    def api(self, method, url, data=None):
        if url == "https://api.github.com/user":
            return {"login": "doctor-user"}
        endpoint = url.split(f"/repos/{REPO}", 1)[1].removeprefix("/").split("?")[0]
        if endpoint == "":
            return {"full_name": REPO, "default_branch": "main"}
        if endpoint == "branches/main":
            return {"commit": {"sha": git(self.repo, "rev-parse", "main")}}
        if endpoint.startswith("git/matching-refs/heads/"):
            ref = "refs/" + endpoint.removeprefix("git/matching-refs/")
            result = subprocess.run(["git", "show-ref", "--verify", ref], cwd=self.repo, capture_output=True, text=True)
            return [{"ref": ref, "object": {"sha": result.stdout.split()[0]}}] if result.returncode == 0 else []
        if endpoint == "pulls/1":
            return self.pr()
        if endpoint == "issues/1/comments":
            if method == "POST":
                row = {"id": len(self.review_requests) + 1, "body": data["body"], "user": {"login": "doctor-user"}}
                self.review_requests.append(row)
                return row
            return list(self.review_requests)
        if endpoint == "pulls/1/reviews":
            return list(self.reviews)
        if endpoint.startswith("pulls/1/reviews/"):
            return self.annotations.get(int(endpoint.split("/")[3]), [])
        if endpoint.startswith("issues/comments/"):
            return self.reactions.get(int(endpoint.split("/")[2]), [])
        if endpoint.endswith("/check-runs"):
            return {"check_runs": [{"name": "tests", "head_sha": self.head(),
                                    "conclusion": "success" if self.ci_success else None}]}
        if endpoint.endswith("/statuses"):
            return []
        if endpoint == "pulls/1/merge":
            self.merge_calls.append(data)
            assert data["sha"] == self.head()
            self.merged = True
            return {"merged": True}
        raise AssertionError(f"Unexpected GitHub call: {method} {endpoint}")


def parse_cli(capsys, *args):
    assert main(list(args)) == 0
    return json.loads(capsys.readouterr().out)


def test_queue_restarts_uses_fixes_and_merges_only_reviewed_head(tmp_path, monkeypatch, capsys, local_repo):
    path = tmp_path / "archive.json"
    monkeypatch.setenv("DADDY_DOCTOR_ARCHIVE_FILE", str(path))
    monkeypatch.setenv("GITHUB_REPO", REPO)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-aaaaaaaaaaaaaaaaaaaaaaaaa")
    monkeypatch.setenv("GITHUB_TOKEN", "test-github-token")
    monkeypatch.delenv("DADDY_ALLOWED_TARGET_REPOS", raising=False)
    for proxy in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(proxy, raising=False)
    github = GitHubStub(local_repo)
    prompts = []
    pushes = []
    original_workspace_init = DoctorWorkspace.__init__
    original_push = DoctorWorkspace.push

    def setup(workspace, root, settings):
        original_workspace_init(workspace, root, settings)
        workspace.url = local_repo.as_uri()

    def push(workspace, branch, commit, previous):
        pushes.append(commit)
        original_push(workspace, branch, commit, previous)
        if len(pushes) == 1:
            raise ConnectionError("Lost push response after Git accepted the commit.")

    def validation(root):
        output = subprocess.run(
            [sys.executable, "-m", "tests.check"], cwd=root, capture_output=True, text=True,
            env={"PYTHONPATH": str(root), "PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"}, check=False,
        )
        return output.returncode == 0, output.stderr

    def decision(*, prompt, **kwargs):
        evidence = json.loads(prompt)
        prompts.append(evidence)
        if len(prompts) == 1:
            assert "answer is wrong" in evidence["feedback"]
            return {"verdict": "approved", "candidate_digest": "", "reason": "Premature result", "edits": []}
        if len(prompts) == 2:
            return {"verdict": "patch", "candidate_digest": "", "reason": "Set the correct answer",
                    "edits": [{"path": "src/example.py", "old": "answer = 0", "new": "answer = 1"}]}
        if evidence["findings"] and not evidence["candidate"]:
            assert "use answer 2" in evidence["findings"][0]
            assert any(item["event"] == "codex_fix_cycle_1" for item in evidence["previous_evidence"])
            return {"verdict": "patch", "candidate_digest": "", "reason": "Resolve Codex finding",
                    "edits": [{"path": "src/example.py", "old": "answer = 1", "new": "answer = 2"}]}
        assert evidence["validation_passed"]
        return {"verdict": "approved", "candidate_digest": evidence["candidate_digest"], "reason": "Verified fix", "edits": []}

    def worker(settings, archive):
        instance = GitHubDoctorWorker(settings, archive, validation_image="test-image",
                                      validation_command="python -m tests.check", required_checks={"tests"})
        original_validator = instance.repair.validator
        instance.repair.validator = validation
        validation.command = original_validator.command
        instance.repair.api.generate_json = decision
        instance.git._api_request = github.api
        instance.git.create_pull_request = github.create
        return instance

    monkeypatch.setattr(DoctorWorkspace, "__init__", setup)
    monkeypatch.setattr(DoctorWorkspace, "push", push)
    monkeypatch.setattr("the_daddy.swarmsy_doctor_queue._worker", worker)

    logs = tmp_path / "logs"
    logs.write_text("OPENAI_API_KEY=sk-test-aaaaaaaaaaaaaaaaaaaaaaaaa")
    parse_cli(capsys, "--enqueue", "Fix the wrong answer", "--log-file", str(logs))
    interrupted = parse_cli(capsys, "--process-once")
    assert "Lost push response" in interrupted["reason"]
    staged = JsonDoctorArchive(path).recent_requests()[0]
    assert staged.pending_head_sha == pushes[0] and not staged.pr_number
    assert not github.review_requests

    assert parse_cli(capsys, "--process-once")["status"] == "pr_opened_waiting_review"
    assert len(pushes) == github.pr_creates == len(github.review_requests) == 1
    with pytest.raises(ValueError):
        DoctorEdit.model_validate({"path": "x", "old": "1", "new": "2", "command": "pytest"})

    first_head = github.head()
    github.reviews = [{"id": 1, "user": BOT, "state": "COMMENTED", "commit_id": first_head}]
    github.annotations = {1: [{"id": 101, "user": BOT, "path": "src/example.py", "body": "Fix: use answer 2."}]}
    github.reactions = {1: [{"user": BOT, "content": "+1"}]}
    assert parse_cli(capsys, "--process-once")["status"] == "pr_opened_waiting_review"
    second_head = github.head()
    assert second_head != first_head and len(github.review_requests) == 2
    assert all("@codex review" in row["body"] and "give the concrete fix" in row["body"] for row in github.review_requests)

    github.reviews.append({"id": 2, "user": BOT, "state": "APPROVED", "commit_id": first_head})
    assert parse_cli(capsys, "--process-once")["status"] == "pr_opened_waiting_review"
    assert not github.merge_calls

    github.reviews.append({"id": 3, "user": BOT, "state": "APPROVED", "commit_id": second_head})
    assert parse_cli(capsys, "--process-once")["status"] == "pr_opened_waiting_review"
    assert not github.merge_calls
    github.ci_success = True
    assert parse_cli(capsys, "--process-once")["status"] == "merged"
    assert [item["sha"] for item in github.merge_calls] == [second_head]
    archived = JsonDoctorArchive(path).recent_requests()[0]
    assert archived.review_cycles == 1
    assert [edit.new for edit in archived.learned_edits] == ["answer = 1", "answer = 2"]
    assert "sk-test-aaaaaaaaaaaaaaaaaaaaaaaaa" not in path.read_text()

    repeat = DoctorRequest(problem_summary="Fix the wrong answer", repo_target=REPO, source="daddy",
                           allowed_paths=["src/", "tests/"])
    restarted = worker(Settings(), JsonDoctorArchive(path))
    remembered = restarted._memory(repeat)
    assert remembered == archived.learned_edits
    checkout = tmp_path / "repeat"
    checkout.mkdir()
    workspace = DoctorWorkspace(checkout, Settings())
    workspace.checkout(git(local_repo, "rev-parse", "main"))
    calls = len(prompts)
    restarted.repair.run(workspace, repeat, [], remembered)
    assert len(prompts) == calls + 1
    assert prompts[-1]["validation_passed"] and "+answer = 2" in prompts[-1]["candidate"]


def test_workspace_validates_scope_and_anchors_before_writing(tmp_path, local_repo):
    workspace = DoctorWorkspace(tmp_path, Settings(github_repo=REPO))
    workspace.root = local_repo
    request = DoctorRequest(problem_summary="Fix answer", repo_target=REPO, source="daddy", allowed_paths=["src/"])
    with pytest.raises(ValueError, match="out of scope"):
        workspace.apply(request, [DoctorEdit(path="src/example.py", old="answer = 0", new="answer = 2"),
                                  DoctorEdit(path=".github/workflows/test.yml", old="", new="new")])
    assert (local_repo / "src/example.py").read_text() == "answer = 0\n"
    with pytest.raises(ValueError, match="match exactly once"):
        workspace.apply(request, [DoctorEdit(path="src/example.py", old="answer = 3", new="answer = 2")])
    assert not workspace.diff()
