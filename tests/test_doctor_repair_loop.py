from __future__ import annotations

import json
import os
import subprocess
import sys
from unittest.mock import Mock

import pytest

from the_daddy.config import Settings
from the_daddy.doctor_repair import CloudRepairUnavailable, DoctorWorkspace, RepairLoop
from the_daddy.doctor_worker import CODEX_BOT, GitHubDoctorWorker
from the_daddy.swarmsy_doctor import DoctorEdit, DoctorRequest, JsonDoctorArchive, MOONBOYS_REPO
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


@pytest.mark.parametrize("delivery", ["normal", "interrupted_push", "stale_pr_head"])
def test_website_revalidates_same_pr_on_new_base(local_repo, tmp_path, monkeypatch, delivery):
    page = local_repo / "games/chain-maze/index.html"
    page.parent.mkdir(parents=True)
    page.write_text('<div id="app">\n')
    git(local_repo, "add", ".")
    git(local_repo, "commit", "-qm", "website")
    old_base = git(local_repo, "rev-parse", "main")

    worker = GitHubDoctorWorker(Settings(github_repo=MOONBOYS_REPO, doctor_telegram_required=True),
                                JsonDoctorArchive(tmp_path / "archive.json"),
                                validation_image="test", validation_command="true", required_checks=set())
    request = DoctorRequest(source="daddy", repo_target=MOONBOYS_REPO, request_id="support-5-11",
                            problem_summary="Add a landmark", allowed_paths=["games/chain-maze/index.html"],
                            base_branch="main", base_sha=old_base, expected_base_sha=old_base, pr_number=42,
                            review_request_id=1, learned_edits=[
                                DoctorEdit(path="games/chain-maze/index.html", old='<div id="app">',
                                           new='<div id="app" role="main">'),
                            ])
    branch = worker._branch(request)
    git(local_repo, "checkout", "-qb", branch)
    page.write_text('<div id="app" role="main">\n')
    git(local_repo, "commit", "-qam", "validated repair")
    old_head = request.head_sha = git(local_repo, "rev-parse", "HEAD")
    git(local_repo, "checkout", "-q", "main")
    (local_repo / "unrelated.txt").write_text("other PR\n")
    git(local_repo, "add", ".")
    git(local_repo, "commit", "-qm", "other PR")
    base = git(local_repo, "rev-parse", "main")

    original_init = DoctorWorkspace.__init__
    original_push = DoctorWorkspace.push

    def setup(workspace, root, settings):
        original_init(workspace, root, settings)
        workspace.url = local_repo.as_uri()

    fail_push = delivery == "interrupted_push"
    stale_pr_head = delivery == "stale_pr_head"

    def push(workspace, *args):
        nonlocal fail_push
        if fail_push:
            fail_push = False
            raise RuntimeError("interrupted push")
        return original_push(workspace, *args)

    def current_pr(*args):
        nonlocal stale_pr_head
        head = git(local_repo, "rev-parse", branch)
        if stale_pr_head and head != old_head:
            head = old_head
            stale_pr_head = False
        return {"state": "open", "draft": False,
                "head": {"repo": {"full_name": MOONBOYS_REPO}, "ref": branch, "sha": head},
                "base": {"repo": {"full_name": MOONBOYS_REPO}, "ref": "main", "sha": base}}

    def validate(root):
        assert (root / "unrelated.txt").read_text() == "other PR\n"
        assert 'role="main"' in (root / request.allowed_paths[0]).read_text()
        return True, "passed"

    monkeypatch.setattr(DoctorWorkspace, "__init__", setup)
    monkeypatch.setattr(DoctorWorkspace, "push", push)
    worker._verify_target = Mock()
    worker._repo = Mock(return_value=("main", base))
    worker._head = Mock(side_effect=lambda _: git(local_repo, "rev-parse", branch))
    worker._api = Mock(side_effect=current_pr)
    worker._request_review = Mock()
    worker.repair.validator = Mock(side_effect=validate)
    worker.telegram.decision = Mock(side_effect=["approved", "invalidated", "invalidated"])

    if delivery == "interrupted_push":
        with pytest.raises(RuntimeError, match="interrupted push"):
            worker.poll_review(request)
        request = worker.archive.get_request(request.request_id)
        assert request.pending_revalidation
    if delivery == "stale_pr_head":
        result = worker.poll_review(request)
        assert "Waiting for GitHub" in result.reason
        assert request.pending_revalidation and request.head_sha == old_head

    result = worker.poll_review(request)
    assert not result.merge_ready
    assert request.pr_number == 42 and request.review_request_id == 0
    assert request.base_sha == base and request.head_sha != old_head
    assert not request.pending_revalidation and len(request.learned_edits) == 1
    assert git(local_repo, "rev-list", "--parents", "-n", "1", branch).split()[1:] == [old_head, base]
    assert git(local_repo, "diff", "--name-only", base, branch) == request.allowed_paths[0]
    worker.repair.validator.assert_called_once()
    worker._request_review.assert_called_once_with(request)


class GitHubStub:
    def __init__(self, repo):
        self.repo = repo
        self.branch = ""
        self.review_requests = []
        self.issue_comments = []
        self.reviews = []
        self.annotations = {}
        self.reactions = {}
        self.ci_success = False
        self.merged = False
        self.merge_sha = "a" * 40
        self.deploy_runs = []
        self.deploy_jobs = []
        self.merge_calls = []
        self.pr_creates = 0

    def head(self):
        return git(self.repo, "rev-parse", f"refs/heads/{self.branch}")

    def pr(self):
        return {
            "number": 1, "state": "closed" if self.merged else "open", "draft": False, "merged": self.merged,
            "merge_commit_sha": self.merge_sha if self.merged else None,
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
            return [*self.review_requests, *self.issue_comments]
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
            return {"merged": True, "sha": self.merge_sha}
        if endpoint == "actions/workflows/deploy-worker.yml/runs":
            assert f"head_sha={self.merge_sha}" in url and "event=push" in url
            return {"workflow_runs": self.deploy_runs}
        if endpoint == "actions/runs/12/jobs":
            return {"jobs": self.deploy_jobs}
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
                                      validation_command="python -m tests.check", required_checks={"tests"},
                                      deploy_workflow="deploy-worker.yml")
        instance.telegram.enabled = True
        instance.telegram.decision = lambda request, action="read": (
            "invalidated" if action == "invalidate" else "approved" if github.ci_success else "missing"
        )
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

    summary = {"code_review": {"commit_sha": second_head, "status": "running",
                              "has_any_findings": None, "has_unresolved_findings": None}}
    github.issue_comments = [{"user": BOT, "body": f"<!-- codex-review-state:v1 {json.dumps(summary)} -->"}]
    assert parse_cli(capsys, "--process-once")["status"] == "pr_opened_waiting_review"
    assert not github.merge_calls
    summary["code_review"].update(status="completed", has_any_findings=False, has_unresolved_findings=False)
    github.issue_comments[0].update(body=f"<!-- codex-review-state:v1 {json.dumps(summary)} -->", updated_at="2026-11-26T22:00:02Z")
    rejected_review = {"id": 3, "user": BOT, "state": "CHANGES_REQUESTED", "commit_id": second_head,
                       "submitted_at": "2026-11-26T22:00:01Z"}
    github.reviews.append(rejected_review)
    assert parse_cli(capsys, "--process-once")["status"] == "pr_opened_waiting_review"
    assert not github.merge_calls
    assert JsonDoctorArchive(path).recent_requests()[0].review_cycles == 1
    github.reviews[-1:] = [
        {"id": 4, "user": BOT, "state": "APPROVED", "commit_id": second_head, "submitted_at": "2026-11-26T22:00:03Z"},
        rejected_review,
    ]
    summary["code_review"].update(has_any_findings=True, has_unresolved_findings=True)
    github.issue_comments[0].update(body=f"<!-- codex-review-state:v1 {json.dumps(summary)} -->", updated_at="2026-11-26T22:00:01Z")
    github.ci_success = True
    assert parse_cli(capsys, "--process-once")["status"] == "merged"
    assert [item["sha"] for item in github.merge_calls] == [second_head]
    github.deploy_runs = [
        {"id": 10, "head_sha": second_head, "event": "push", "head_branch": "main", "status": "completed", "conclusion": "success"},
        {"id": 11, "head_sha": github.merge_sha, "event": "pull_request", "head_branch": "main", "status": "completed", "conclusion": "success"},
    ]
    assert parse_cli(capsys, "--process-once")["deployment_status"] == "pending"
    github.deploy_runs.append({"id": 12, "head_sha": github.merge_sha, "event": "push", "head_branch": "main",
                               "status": "completed", "conclusion": "success"})
    github.deploy_jobs = [{"name": "deploy / Cloudflare deploy", "conclusion": "success"}]
    deployed = parse_cli(capsys, "--process-once")
    assert deployed["deployment_status"] == "deployed"
    assert deployed["deployment_url"].endswith("/actions/runs/12")
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


def test_candidate_file_limit_applies_across_batches_and_replays(tmp_path, local_repo):
    settings = Settings(github_repo=REPO)
    request = DoctorRequest(problem_summary="Fix answer", repo_target=REPO, source="daddy", allowed_paths=["src/"])
    workspace = DoctorWorkspace(local_repo, settings)
    first = [DoctorEdit(path=f"src/part_{i}.py", old="", new="value = 1\n") for i in range(3)]
    second = [DoctorEdit(path=f"src/part_{i}.py", old="", new="value = 2\n") for i in range(3, 6)]
    workspace.apply(request, first)
    with pytest.raises(ValueError, match="too many files"):
        workspace.apply(request, second)
    workspace.apply(request, second[:2])
    original_diff = workspace.diff()
    workspace.reset()
    workspace.apply(request, [*first, *second[:2]])
    assert workspace.diff() == original_diff


def test_replay_limit_counts_paths_reverted_between_api_batches(monkeypatch, local_repo):
    monkeypatch.setattr("the_daddy.doctor_repair.MAX_CHANGED_FILES", 2)
    settings = Settings(github_repo=REPO, max_attempts=5, openai_api_key="")
    request = DoctorRequest(problem_summary="Fix answer", repo_target=REPO, source="daddy", allowed_paths=["src/"])
    workspace = DoctorWorkspace(local_repo, settings)
    loop = RepairLoop(settings, lambda _root: (True, "tests passed"), lambda _request: None)
    patches = iter([
        [{"path": "src/example.py", "old": "answer = 0", "new": "answer = 1"},
         {"path": "src/additional.py", "old": "", "new": "value = 2\n"}],
        [{"path": "src/example.py", "old": "answer = 1", "new": "answer = 0"}],
        [{"path": "src/third.py", "old": "", "new": "value = 3\n"}],
        [{"path": "src/example.py", "old": "answer = 0", "new": "answer = 2"}],
    ])

    def decision(*, prompt, **_kwargs):
        evidence = json.loads(prompt)
        edits = next(patches, None)
        if edits is None:
            return {"verdict": "approved", "candidate_digest": evidence["candidate_digest"], "reason": "Fixed", "edits": []}
        return {"verdict": "patch", "candidate_digest": "", "reason": "Fix", "edits": edits}

    loop.api.generate_json = decision
    final_edits, _ = loop.run(workspace, request, [], [])
    assert final_edits == [DoctorEdit(path="src/example.py", old="answer = 0", new="answer = 2")]
    assert any(item["event"] == "patch_rejected" and "replayable files" in item["detail"] for item in request.repair_log)


@pytest.mark.parametrize("local_result", ["valid", "blocked", "invalid", "unsafe", "wrong_anchor", "failed_validation"])
def test_local_proposal_escalates_and_requires_cloud_approval(local_repo, local_result):
    settings = Settings(github_repo=REPO, max_attempts=5, openai_api_key="", doctor_local_ai=True)
    request = DoctorRequest(problem_summary="Fix answer", repo_target=REPO, source="daddy", allowed_paths=["src/"])
    workspace = DoctorWorkspace(local_repo, settings)
    def validate(root):
        return ("answer = 2" in (root / "src/example.py").read_text(), "test output")
    loop = RepairLoop(settings, validate, lambda _request: None)
    local_calls, cloud_calls = [], []
    def patch(old="answer = 0", new="answer = 2", path="src/example.py"):
        return {"verdict": "patch", "candidate_digest": "", "reason": "Fix",
                "edits": [{"path": path, "old": old, "new": new}]}
    def local(**kwargs):
        local_calls.append(kwargs)
        return {
            "valid": patch(), "blocked": None, "invalid": {"verdict": "patch"},
            "unsafe": patch(path=".env"), "wrong_anchor": patch(old="not present"),
            "failed_validation": patch(new="answer = 1"),
        }[local_result]
    def cloud(*, prompt, **kwargs):
        evidence = json.loads(prompt)
        cloud_calls.append(evidence)
        if evidence["validation_passed"]:
            return {"verdict": "approved", "candidate_digest": evidence["candidate_digest"],
                    "reason": "Verified", "edits": []}
        return patch(old="answer = 1" if evidence["candidate"] else "answer = 0")
    loop.local_api.propose = local
    loop.api.generate_json = cloud
    edits, digest = loop.run(workspace, request, [], [])
    assert edits and digest
    assert len(local_calls) == 1
    assert cloud_calls[-1]["validation_passed"] is True
    assert len(cloud_calls) == (1 if local_result == "valid" else 2)
    assert (local_repo / "src/example.py").read_text() == "answer = 2\n"


def test_local_proposal_cannot_approve_candidate(local_repo):
    settings = Settings(github_repo=REPO, max_attempts=3, openai_api_key="", doctor_local_ai=True)
    request = DoctorRequest(problem_summary="Fix answer", repo_target=REPO, source="daddy", allowed_paths=["src/"])
    workspace = DoctorWorkspace(local_repo, settings)
    loop = RepairLoop(settings, lambda _root: (True, "ok"), lambda _request: None)
    loop.local_api.propose = lambda **kw: {"verdict": "approved", "candidate_digest": "", "reason": "no", "edits": []}
    calls = []
    def cloud(*, prompt, **kwargs):
        calls.append(prompt)
        return {"verdict": "blocked", "candidate_digest": "", "reason": "No patch", "edits": []}
    loop.api.generate_json = cloud
    with pytest.raises(RuntimeError, match="exhausted"):
        loop.run(workspace, request, [], [])
    assert calls
    assert not workspace.diff()


@pytest.mark.parametrize("mode", [
    "passing_local", "failing_local", "no_candidate", "codex_patch", "bad_codex_patch",
    "cli_patch", "bad_cli_patch", "wrong_cli_head",
])
def test_missing_openai_fallback_requires_passing_scoped_candidate(local_repo, mode, monkeypatch):
    settings = Settings(github_repo=REPO, max_attempts=3, openai_api_key="",
                        doctor_local_ai=True, doctor_codex_fallback=True,
                        doctor_codex_cli_fallback=mode.endswith("cli_patch") or mode == "wrong_cli_head")
    request = DoctorRequest(problem_summary="Fix answer", repo_target=REPO,
                            source="daddy", allowed_paths=["src/"])
    workspace = DoctorWorkspace(local_repo, settings)
    if settings.doctor_codex_cli_fallback:
        request.pr_number = 121
        request.head_sha = "f" * 40 if mode == "wrong_cli_head" else workspace.git("rev-parse", "HEAD").strip()
    def validate(root):
        return ("answer = 2" in (root / "src/example.py").read_text(), "test output")
    loop = RepairLoop(settings, validate, lambda _: None)
    edit = DoctorEdit(path="src/example.py", old="answer = 0",
                      new="answer = 1" if mode in ("failing_local", "bad_codex_patch", "bad_cli_patch") else "answer = 2")
    loop.local_api.propose = lambda **kw: (
        {"verdict": "patch", "candidate_digest": "", "reason": "Fix", "edits": [edit.model_dump()]}
        if mode in ("passing_local", "failing_local") else None
    )
    def unexpected_cloud(**kw):
        pytest.fail("Missing credentials must not trigger an OpenAI request")
    loop.api.generate_json = unexpected_cloud
    options = {"codex_edits": [edit]} if mode in ("codex_patch", "bad_codex_patch") else {}
    attempts = []
    def cli(head, evidence):
        attempts.append(head)
        assert "src/example.py" in evidence["files"]
        return [edit]
    monkeypatch.setattr("the_daddy.doctor_repair.propose_codex_edits", cli)
    findings = ["Fix remaining defect"] if options or settings.doctor_codex_cli_fallback else []
    if mode in ("passing_local", "codex_patch", "cli_patch"):
        edits, digest = loop.run(workspace, request, findings, [], **options)
        assert edits == [edit] and digest
        assert request.pending_codex_only is True
        assert not any(item["event"] == "api_approved" for item in request.repair_log)
    else:
        with pytest.raises(CloudRepairUnavailable):
            loop.run(workspace, request, findings, [], **options)
        assert request.pending_codex_only is False
    assert attempts == ([request.head_sha] if mode in ("cli_patch", "bad_cli_patch") else [])
