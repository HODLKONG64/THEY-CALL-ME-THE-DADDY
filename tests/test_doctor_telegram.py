from unittest.mock import Mock

import pytest

from the_daddy.config import Settings
from the_daddy.doctor_telegram import TelegramApproval
from the_daddy.doctor_worker import GitHubDoctorWorker
from the_daddy.swarmsy_doctor import DoctorRequest, DoctorEdit, JsonDoctorArchive

REPO = "HODLKONG64/THEY-CALL-ME-THE-DADDY"


@pytest.fixture
def request_record():
    return DoctorRequest(source="daddy", repo_target=REPO, problem_summary="Fix example",
                         allowed_paths=["src/example.py"], head_sha="a"*40, base_sha="b"*40,
                         base_branch="main", pr_number=42, review_request_id=1,
                         swarmsy_pr_url=f"https://github.com/{REPO}/pull/42",
                         learned_edits=[DoctorEdit(path="src/example.py", old="a", new="b")])


@pytest.fixture
def worker(tmp_path, request_record):
    w = GitHubDoctorWorker(Settings(github_repo=REPO, doctor_telegram_required=True),
                           JsonDoctorArchive(tmp_path/"repairs.json"),
                           validation_image="test", validation_command="pytest", required_checks={"test"})
    w._verify_target = Mock()
    w._verify_pr = Mock()
    w._repo = Mock(return_value=("main", request_record.base_sha))
    w._api = Mock(return_value={"state": "open", "draft": False, "merged": False,
                                "base": {"sha": request_record.base_sha},
                                "mergeable": True, "mergeable_state": "clean"})
    w._request_review = Mock()
    w._codex_review = Mock(return_value=("approved", []))
    w._ci_review = Mock(return_value=(True, []))
    w.telegram.decision = Mock(return_value="ready")
    w.git.merge_pull_request = Mock(return_value={"merged": True, "sha": "c"*40})
    w._record_merge = Mock()
    return w


@pytest.mark.parametrize("decision", ["missing", "ready", "unavailable", "invalidated", "fix_requested"])
def test_nonapproval_never_merges(worker, request_record, decision):
    worker.telegram.decision.return_value = decision
    assert not worker.merge_pr(request_record, request_record.swarmsy_pr_url)
    worker.git.merge_pull_request.assert_not_called()


def test_rejected_keeps_pr_unmerged(worker, request_record):
    worker.telegram.decision.return_value = "rejected"
    with pytest.raises(PermissionError, match="Owner rejected"):
        worker.merge_pr(request_record, request_record.swarmsy_pr_url)
    worker.git.merge_pull_request.assert_not_called()


def test_further_fix_is_actionable(worker, request_record):
    worker.telegram.decision.return_value = "fix_requested"
    attempt = worker.poll_review(request_record)
    assert not attempt.merge_ready
    assert attempt.review_verdict == "changes_requested"
    assert attempt.review_comments[0].author == "Telegram owner"


def test_final_approval_rechecked(worker, request_record):
    worker.telegram.decision.side_effect = ["approved", "unavailable"]
    assert not worker.merge_pr(request_record, request_record.swarmsy_pr_url)
    worker.git.merge_pull_request.assert_not_called()
    worker.telegram.decision.side_effect = None
    worker.telegram.decision.return_value = "approved"
    assert worker.merge_pr(request_record, request_record.swarmsy_pr_url)
    worker.git.merge_pull_request.assert_called_once_with(42, head_sha=request_record.head_sha)


def test_ci_and_base_invalidate(worker, request_record):
    worker._ci_review.return_value = (False, [])
    assert not worker.poll_review(request_record).merge_ready
    worker.telegram.decision.assert_called_with(request_record, "invalidate")
    worker._repo.return_value = ("main", "d"*40)
    with pytest.raises(PermissionError):
        worker.poll_review(request_record)
    worker.telegram.decision.assert_called_with(request_record, "invalidate")


def test_transport_rejects_stale_commit_and_missing_token(tmp_path, monkeypatch, request_record):
    monkeypatch.delenv("DOCTOR_APPROVAL_TOKEN", raising=False)
    client = TelegramApproval(tmp_path/"archive.json", True)
    assert client.decision(request_record) == "unavailable"
    client._post = Mock(return_value={"state": "approved", "head_sha": "d"*40,
                                     "base_sha": request_record.base_sha, "revision": 1})
    assert client.decision(request_record) == "unavailable"
    client._post.return_value["head_sha"] = request_record.head_sha
    assert client.decision(request_record) == "approved"


def test_outbox_survives_restart_and_deduplicates(tmp_path, monkeypatch, request_record):
    monkeypatch.setenv("DOCTOR_APPROVAL_TOKEN", "a"*64)
    path = tmp_path/"archive.json"
    client = TelegramApproval(path, True)
    client.emit(request_record, "running")
    client.emit(request_record, "running")
    client._post = Mock(return_value={})
    client.flush()
    restarted = TelegramApproval(path, True)
    restarted._post = Mock(return_value={"ok": True})
    restarted.flush()
    restarted.flush()
    events = [call.args[0] for call in restarted._post.call_args_list if call.args[0]["action"] == "event"]
    assert len(events) == 1
    assert events[0]["event"] == "running"
