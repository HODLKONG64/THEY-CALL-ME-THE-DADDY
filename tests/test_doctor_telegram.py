import json
from unittest.mock import Mock

import httpx
import pytest

from the_daddy.config import Settings
from the_daddy.doctor_telegram import TelegramApproval
from the_daddy.doctor_worker import CODEX_BOT, GitHubDoctorWorker
from the_daddy.doctor_repair import CloudRepairUnavailable
from the_daddy.swarmsy_doctor import DoctorRequest, DoctorEdit, DoctorReviewComment, JsonDoctorArchive

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


def test_disabled_telegram_blocks_merge_but_preserves_ci_repair_findings(worker, request_record):
    worker.telegram.enabled = False
    finding = DoctorReviewComment(author="GitHub CI", body="A required check failed.")
    worker._ci_review.return_value = (False, [finding])
    attempt = worker.poll_review(request_record)
    assert attempt.review_comments == [finding]
    assert attempt.review_verdict == "changes_requested"
    assert not attempt.merge_ready
    assert not worker.merge_pr(request_record, request_record.swarmsy_pr_url)
    worker.git.merge_pull_request.assert_not_called()


def test_final_approval_rechecked(worker, request_record):
    worker.telegram.decision.side_effect = ["approved", "unavailable"]
    assert not worker.merge_pr(request_record, request_record.swarmsy_pr_url)
    worker.git.merge_pull_request.assert_not_called()
    worker.telegram.decision.side_effect = None
    worker.telegram.decision.return_value = "approved"
    assert worker.merge_pr(request_record, request_record.swarmsy_pr_url)
    worker.git.merge_pull_request.assert_called_once_with(42, head_sha=request_record.head_sha)


def test_base_is_rechecked_after_review_before_merge(worker, request_record):
    worker._repo.side_effect = [("main", request_record.base_sha), ("main", "d"*40)]
    worker.telegram.decision.return_value = "approved"
    assert not worker.merge_pr(request_record, request_record.swarmsy_pr_url)
    worker.telegram.decision.assert_called_with(request_record, "invalidate")
    worker.git.merge_pull_request.assert_not_called()


def test_fallback_request_asks_for_structured_answer_without_a_review_command(worker, request_record):
    worker._list = Mock(return_value=[])
    worker._api = Mock(return_value={"id": 90})
    worker.git._api_request = Mock(return_value={"login": "doctor"})
    worker._request_codex_patch(request_record)
    method, endpoint, data = worker._api.call_args.args
    assert (method, endpoint) == ("POST", "issues/42/comments")
    assert data["body"].startswith("@codex What exact text changes")
    assert "DOCTOR_PATCH " + request_record.head_sha in data["body"]
    assert request_record.review_request_id == 90


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


def test_merge_receipt_survives_restart_and_requires_exact_ack(tmp_path, monkeypatch, request_record):
    monkeypatch.setenv("DOCTOR_APPROVAL_TOKEN", "a"*64)
    path = tmp_path / "archive.json"
    request_record.merge_sha = "f"*40
    client = TelegramApproval(path, True)
    client.record_merge(request_record)
    client.record_merge(request_record)
    client._post = Mock(return_value={})
    client.flush()

    restarted = TelegramApproval(path, True)
    ack = {"state": "merged", "head_sha": request_record.head_sha, "base_sha": request_record.base_sha}
    restarted._post = Mock(return_value=ack)
    restarted.flush()
    restarted._post.return_value = {**ack, "merge_sha": request_record.merge_sha}
    restarted.flush()
    restarted.flush()
    receipts = [call.args[0] for call in restarted._post.call_args_list if call.args[0]["action"] == "merged"]
    assert receipts == [
        {"action": "merged", **restarted.identity(request_record), "merge_sha": request_record.merge_sha}
    ] * 2


def test_unacknowledged_merge_receipts_do_not_starve_new_ones(tmp_path, monkeypatch, request_record):
    monkeypatch.setenv("DOCTOR_APPROVAL_TOKEN", "a"*64)
    client = TelegramApproval(tmp_path / "archive.json", True)
    for number in range(1, 10):
        client.record_merge(request_record.model_copy(update={"pr_number": number, "merge_sha": "f"*40}))
    client._post = Mock(return_value={})
    client.flush()
    client.flush()
    attempts = [call.args[0]["pr_number"] for call in client._post.call_args_list
                if call.args[0]["action"] == "merged"]
    assert attempts[:9] == list(range(1, 10))


@pytest.mark.parametrize("author, decisions", [
    ("Codex", ["approved", "unavailable"]),
    ("Telegram owner", ["unavailable"]),
])
def test_wait_only_approval_paths_restore_repair_budget(worker, request_record, author, decisions):
    worker._stage = Mock()
    worker.telegram.decision.side_effect = decisions
    request_record.review_cycles = 3
    worker.archive.upsert_request(request_record)
    attempt = worker.apply_review_comment_fixes(
        request_record, [DoctorReviewComment(author=author, body="Check remaining defect")], 3,
    )
    assert not attempt.merge_ready
    worker._stage.assert_not_called()
    assert request_record.review_cycles == 2
    assert worker.archive.get_request(request_record.request_id).review_cycles == 2


def test_transport_uses_explicit_application_user_agent(tmp_path, monkeypatch, request_record):
    monkeypatch.setenv("DOCTOR_APPROVAL_TOKEN", "a"*64)
    real_client = httpx.Client
    seen = []

    def handler(req):
        assert req.headers["User-Agent"] == "Moonboys-Doctor/1.0"
        assert req.headers["X-Doctor-Approval-Token"] == "a"*64
        seen.append(req)
        return httpx.Response(200, json={"state": "approved", "head_sha": request_record.head_sha,
                                         "base_sha": request_record.base_sha, "revision": 1})

    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("the_daddy.doctor_telegram.httpx.Client", client)
    assert TelegramApproval(tmp_path/"archive.json", True).decision(request_record) == "approved"
    assert len(seen) == 1


def patch_body(head, path="src/example.py"):
    return "DOCTOR_PATCH " + head + "\n```json\n" + json.dumps([
        {"path": path, "old": "b", "new": "c"}
    ]) + "\n```"


@pytest.mark.parametrize("case", ["fresh", "stale", "wrong_head", "human", "protected", "ambiguous", "clean"])
def test_pending_codex_patch_requires_fresh_authenticated_scoped_proposal(worker, request_record, case):
    worker.settings.doctor_codex_fallback = True
    head = request_record.head_sha
    request_record.codex_patch_requested_head = head
    anchor = {"id": 1, "body": f"<!-- doctor-patch-request:{head} -->",
              "created_at": "2026-11-28T00:00:00Z"}
    bot = {"login": CODEX_BOT, "type": "Bot"}
    proposal = {"id": 2, "created_at": "2026-11-28T00:00:01Z", "user": bot,
                "body": patch_body(head)}
    if case == "stale":
        proposal["created_at"] = anchor["created_at"]
    elif case == "wrong_head":
        proposal["body"] = patch_body("d"*40)
    elif case == "human":
        proposal["user"] = {"login": CODEX_BOT, "type": "User"}
    elif case == "protected":
        proposal["body"] = patch_body(head, "src/the_daddy/doctor_worker.py")
    elif case == "clean":
        proposal["body"] = f"DOCTOR_REVIEW_APPROVED {head}"
    comments = [anchor, proposal]
    if case == "ambiguous":
        comments.append(dict(proposal, id=3))
    worker._list = Mock(side_effect=lambda endpoint: comments if endpoint == "issues/42/comments" else [])
    worker.telegram.decision.return_value = "approved"
    attempt = worker.poll_review(request_record)
    assert not attempt.merge_ready
    assert bool(attempt.review_comments) == (case == "fresh")
    worker._codex_review.assert_not_called()
    worker.git.merge_pull_request.assert_not_called()
    assert not worker.merge_pr(request_record, request_record.swarmsy_pr_url)
    worker.git.merge_pull_request.assert_not_called()


def test_failed_concrete_codex_patch_consumes_cycle(worker, request_record):
    worker.settings.doctor_codex_fallback = True
    worker.telegram.decision.return_value = "invalidated"
    request_record.review_cycles = 2
    worker._stage = Mock(side_effect=CloudRepairUnavailable("No passing candidate"))
    worker._request_codex_patch = Mock()
    with pytest.raises(PermissionError, match="Codex patch did not produce"):
        worker.apply_review_comment_fixes(request_record, [
            DoctorReviewComment(author=CODEX_BOT, body=patch_body(request_record.head_sha))
        ], 2)
    assert request_record.review_cycles == 2
    worker._request_codex_patch.assert_not_called()
    worker.git.merge_pull_request.assert_not_called()


def test_waiting_for_codex_patch_preserves_budget(worker, request_record):
    worker.settings.doctor_codex_fallback = True
    worker.telegram.decision.return_value = "invalidated"
    request_record.review_cycles = 2
    worker._stage = Mock(side_effect=CloudRepairUnavailable("No passing candidate"))
    worker._request_codex_patch = Mock()
    attempt = worker.apply_review_comment_fixes(request_record, [
        DoctorReviewComment(author=CODEX_BOT, body="Fix remaining defect")
    ], 2)
    assert not attempt.merge_ready
    assert request_record.review_cycles == 1
    assert worker.archive.get_request(request_record.request_id).review_cycles == 1
    worker._request_codex_patch.assert_called_once_with(request_record)


def test_cli_failure_blocks_instead_of_requesting_legacy_patch(worker, request_record):
    worker.settings.doctor_codex_fallback = True
    worker.settings.doctor_codex_cli_fallback = True
    worker.telegram.decision.return_value = "invalidated"
    worker._stage = Mock(side_effect=CloudRepairUnavailable("No passing candidate"))
    worker._request_codex_patch = Mock()
    worker._publish = Mock()
    with pytest.raises(PermissionError, match="Codex CLI fallback did not produce a passing candidate"):
        worker.apply_review_comment_fixes(request_record, [
            DoctorReviewComment(author=CODEX_BOT, body="Fix remaining defect")
        ], 1)
    worker._request_codex_patch.assert_not_called()
    worker._publish.assert_not_called()
