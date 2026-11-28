from unittest.mock import Mock

import pytest

from the_daddy.agents.codex_repair import CodexLiveVerdict
from the_daddy.config import Settings
from the_daddy.doctor_release_review import BrainReviewStore
from the_daddy.doctor_worker import GitHubDoctorWorker
from the_daddy.swarmsy_doctor import DoctorEdit, DoctorRequest, JsonDoctorArchive, MOONBOYS_REPO


@pytest.fixture
def release(tmp_path):
    worker = GitHubDoctorWorker(
        Settings(github_repo=MOONBOYS_REPO, doctor_telegram_required=True, doctor_release_review_required=True),
        JsonDoctorArchive(tmp_path / "archive.json"),
        validation_image="test", validation_command="true", required_checks=set(),
    )
    path = "games/dead-run/index.html"
    request = DoctorRequest(
        request_id="support-5-18", repo_target=MOONBOYS_REPO, source="daddy", problem_summary="Add a landmark",
        pr_number=42, head_sha="a" * 40, base_sha="b" * 40, base_branch="main",
        allowed_paths=[path], learned_edits=[DoctorEdit(path=path, old="<div>", new='<div role="main">')],
    )
    return worker, request


def test_brain_verdict_is_exact_and_persistent(release):
    worker, request = release
    worker.brain_reviews.record(request, "approved", "Change remains in scope.")
    store = BrainReviewStore(worker.archive.path)
    assert store.read(request) == ("approved", "Change remains in scope.")
    assert store.read(request.model_copy(update={"head_sha": "1" * 40}))[0] == "pending"
    assert store.read(request.model_copy(update={"base_sha": "2" * 40}))[0] == "pending"


def test_brain_verdict_is_required_before_telegram_options(release, monkeypatch):
    worker, request = release
    worker._verify_target = Mock()
    worker._verify_pr = Mock()
    worker._repo = Mock(return_value=("main", request.base_sha))
    worker._api = Mock(return_value={"state": "open", "base": {"sha": request.base_sha},
                                     "mergeable": True, "mergeable_state": "clean"})
    worker._request_review = Mock()
    worker._codex_review = Mock(return_value=("approved", []))
    worker._ci_review = Mock(return_value=(True, []))
    monkeypatch.setattr("the_daddy.doctor_worker.exact_ci", lambda *_, **__: ("passed", "", []))
    worker.telegram.decision = Mock(return_value="ready")
    assert "Waiting for Brain" in worker.poll_review(request).reason
    worker.telegram.decision.assert_called_once_with(request, "invalidate")
    worker.brain_reviews.record(request, "approved", "One scoped edit.")
    assert not worker.poll_review(request).merge_ready
    worker.telegram.decision.assert_called_with(request, "ready", allow_auto=True)


@pytest.mark.parametrize("auto,advanced", [(True, False), (False, False), (True, True)])
def test_live_rejection_only_queues_exact_owner_authorized_rollback(release, monkeypatch, auto, advanced):
    worker, request = release
    request.status = "merged"
    request.merge_sha = "c" * 40
    request.deployment_status = "deployed"
    request.live_review_status = "pending"
    request.auto_release = auto
    branch = request.merge_sha if not advanced else "d" * 40
    worker._repo = Mock(side_effect=[("main", request.merge_sha), ("main", branch)] * 2)
    worker._live_release_evidence = Mock(return_value={"probes": [{"matches_commit": True}]})
    monkeypatch.setattr("the_daddy.doctor_worker.review_live_release", lambda commit, _:
                        CodexLiveVerdict(merge_sha=commit, safe=False, reason="Observed a scoped regression."))
    worker.poll_live_review(request)
    rollback = worker.archive.get_request(request.request_id + "-rollback")
    if auto and not advanced:
        assert request.live_review_status == "rollback_queued"
        assert rollback.expected_base_sha == request.merge_sha
        assert rollback.rollback_edits[0].new == request.learned_edits[0].old
        worker.telegram.approval = Mock(return_value=("merged", "auto"))
        assert worker._rollback_authorized(rollback)
        worker.telegram.approval.return_value = ("merged", "manual")
        assert not worker._rollback_authorized(rollback)
    else:
        assert request.live_review_status == "needs_review"
        assert rollback is None
