from unittest.mock import Mock

import pytest

from the_daddy.config import Settings, _DADDY_REPO, _normalize_repo_slug
from the_daddy.doctor_ci import MERGE_LABEL, PAUSE_LABEL, REPAIR_LABEL, exact_ci
from the_daddy.doctor_repair import RepairLoop
from the_daddy.doctor_worker import GitHubDoctorWorker
from the_daddy.swarmsy_doctor import DoctorRequest, JsonDoctorArchive, MOONBOYS_REPO
from the_daddy.swarmsy_doctor_queue import _process_once

BASE = "a" * 40
HEAD = "b" * 40
APP = "games/chain-maze/index.html"


def make_worker(tmp_path, *, dispatch=False, repo=MOONBOYS_REPO):
    settings = Settings(github_repo=repo, allowed_target_repos=frozenset({repo}))
    return GitHubDoctorWorker(settings, JsonDoctorArchive(tmp_path / "archive.json"),
                              validation_image="tests", validation_command="true", required_checks={"tests"},
                              watch_ci=True, dispatch_ci=dispatch)


def pr(number=5, *, draft=False, labels=(REPAIR_LABEL, MERGE_LABEL)):
    return {"number": number, "draft": draft, "labels": [{"name": label} for label in labels], "state": "open",
            "head": {"sha": HEAD, "ref": f"topic-{number}", "repo": {"full_name": MOONBOYS_REPO}},
            "base": {"sha": BASE, "ref": "main", "repo": {"full_name": MOONBOYS_REPO}},
            "mergeable": True, "mergeable_state": "clean"}


def test_exact_workflow_matches_sha_event_and_latest_attempt(tmp_path):
    worker = make_worker(tmp_path)
    worker._list = Mock(side_effect=[
        [{"id": 90, "head_sha": BASE, "head_branch": "topic-5", "event": "workflow_dispatch", "status": "completed",
          "conclusion": "success"},
         {"id": 91, "head_sha": HEAD, "head_branch": "topic-5", "event": "workflow_dispatch", "status": "completed",
          "conclusion": "failure", "run_attempt": 2}],
        [{"id": 44, "name": "Arcade", "status": "completed", "conclusion": "failure",
          "steps": [{"name": "Run complete domain tests (no changed-file filtering)", "conclusion": "failure"}]}],
    ])
    status, url, findings = exact_ci(worker, HEAD, "topic-5")
    assert status == "failed" and url.endswith("/91")
    assert worker._list.call_args.args[0] == "actions/runs/91/attempts/2/jobs"
    assert len(findings) == 1 and "/job/44" in findings[0].body


def test_discovery_reports_paused_and_adopts_only_safe_selected_pr(tmp_path, monkeypatch):
    worker = make_worker(tmp_path)
    worker._repo = Mock(return_value=("main", BASE))
    foreign = pr(9)
    foreign["head"]["repo"]["full_name"] = "somewhere/fork"
    rows = [pr(), pr(6, labels=(REPAIR_LABEL, PAUSE_LABEL)), pr(7, draft=True), pr(8), foreign]

    def api(method, endpoint):
        assert method == "GET"
        if endpoint.startswith("pulls?"):
            return rows
        if endpoint.startswith("compare/"):
            return {"merge_base_commit": {"sha": BASE}}
        if endpoint.startswith("pulls/5/files"):
            return [{"filename": APP, "status": "modified"}]
        assert endpoint.startswith("pulls/8/files")
        return [{"filename": ".github/workflows/production.yml", "status": "modified"}]

    worker._api = Mock(side_effect=api)
    monkeypatch.setattr("the_daddy.doctor_worker.exact_ci", lambda *a, **kw: ("failed", "", []))
    assert len(worker.discover_ci_repairs()) == 5 and not worker.archive.path.exists()
    result = worker.discover_ci_repairs(enqueue=True)
    assert [(item["ci"], item["paused"]) for item in result] == [
        ("queued", False), ("failed", True), ("failed", True), ("needs_manual_scope", False), ("unavailable", False),
    ]
    assert worker.archive.get_request(f"ci-pr-{_normalize_repo_slug(MOONBOYS_REPO)}-5").allowed_paths == [APP]
    assert worker.discover_ci_repairs(enqueue=True)[0]["ci"] == "tracked"


def test_shared_archive_keeps_same_pr_number_in_both_repositories(tmp_path):
    website = make_worker(tmp_path)
    daddy = make_worker(tmp_path, repo=_DADDY_REPO)
    for worker, path in ((website, APP), (daddy, "src/the_daddy/runtime/error_digest.py")):
        worker._api = Mock(side_effect=[
            {"merge_base_commit": {"sha": BASE}},
            [{"filename": path, "status": "modified"}],
        ])
        assert worker._adopt_ci_pr(pr(), BASE, "main", []) == "queued"
    queued = website.archive.list_queued_requests()
    assert {request.repo_target for request in queued} == {MOONBOYS_REPO, _DADDY_REPO}
    assert len({request.request_id for request in queued}) == 2


def test_adopted_pr_cannot_merge_without_label_or_exact_green_ci(tmp_path, monkeypatch):
    worker = make_worker(tmp_path)
    request = DoctorRequest(source="daddy", repo_target=MOONBOYS_REPO,
                            request_id="ci-pr-5", problem_summary="Fix functional CI failure",
                            ci_branch="topic-5", ci_origin_pr=5, pr_number=5, base_branch="main",
                            base_sha=BASE, head_sha=HEAD, allowed_paths=[APP],
                            learned_edits=[{"path": APP, "old": "before", "new": "after"}])
    worker._repo = Mock(return_value=("main", BASE))
    worker._request_review = Mock()
    worker._codex_review = Mock(return_value=("approved", []))
    worker._ci_review = Mock(return_value=(True, []))
    worker._api = Mock(return_value=pr(labels=(REPAIR_LABEL,)))
    monkeypatch.setattr("the_daddy.doctor_worker.exact_ci", lambda *a, **kw: ("passed", "", []))
    assert not worker.poll_review(request).merge_ready
    worker._api.return_value = pr()
    assert worker.poll_review(request).merge_ready
    monkeypatch.setattr("the_daddy.doctor_worker.exact_ci", lambda *a, **kw: ("missing", "", []))
    assert not worker.poll_review(request).merge_ready


def test_post_merge_dispatch_and_follow_up_are_bound_and_deduplicated(tmp_path, monkeypatch):
    worker = make_worker(tmp_path, dispatch=True)
    worker._repo = Mock(return_value=("main", BASE))
    request = DoctorRequest(source="daddy", repo_target=MOONBOYS_REPO, pr_number=5, problem_summary="Original",
                            status="merged", allowed_paths=[APP])
    worker._record_merge(request, BASE, "main")
    worker._api = Mock(side_effect=[{"commit": {"sha": BASE}}, None])
    check = Mock(return_value=("missing", "", []))
    monkeypatch.setattr("the_daddy.doctor_worker.exact_ci", check)
    worker.poll_merged_ci(request)
    worker.poll_merged_ci(request)
    assert check.call_args.kwargs == {"merged": True}
    assert worker._api.call_count == 2
    assert request.post_merge_ci == "pending"
    check.return_value = ("failed", "ci-report", [])
    worker.poll_merged_ci(request)
    worker.poll_merged_ci(request)
    assert request.post_merge_ci == "follow_up_queued"
    follow_up_id = f"ci-follow-up-{_normalize_repo_slug(MOONBOYS_REPO)}-{BASE}"
    assert worker.archive.get_request(follow_up_id).expected_base_sha == BASE
    assert len(worker.archive.list_queued_requests()) == 1
    worker._repo.return_value = ("main", HEAD)
    worker.poll_merged_ci(request)
    assert request.post_merge_ci == "needs_review"


def test_disabling_ci_leaves_repairs_and_deployments_schedulable(tmp_path, monkeypatch):
    worker = make_worker(tmp_path)
    archive = worker.archive
    pending = DoctorRequest(request_id="pending", source="daddy", repo_target=MOONBOYS_REPO,
                            status="merged", problem_summary="Pending after merge", post_merge_ci="pending",
                            updated_at="2026-01-01T00:00:00+00:00")
    deployment = pending.model_copy(update={"request_id": "deploy", "deployment_status": "pending",
                                            "updated_at": "2026-02-01T00:00:00+00:00"})
    repair = pending.model_copy(update={"request_id": "repair", "status": "queued",
                                         "updated_at": "2026-03-01T00:00:00+00:00"})
    for item in (pending, deployment, repair):
        archive.upsert_request(item)
    monkeypatch.setenv("DADDY_DOCTOR_WATCH_CI", "false")
    monkeypatch.setattr("the_daddy.swarmsy_doctor_queue._worker", lambda *args: worker)
    worker.poll_merged_ci = Mock()
    worker.poll_deployment = Mock()
    assert _process_once(archive, worker.settings)["request_id"] == "deploy"
    worker.poll_deployment.assert_called_once()
    worker.poll_merged_ci.assert_not_called()
    archive.upsert_request(deployment.model_copy(update={"deployment_status": "deployed"}))
    assert _process_once(archive, worker.settings)["request_id"] == "repair"
    assert archive.get_request("pending").post_merge_ci == "pending"
    monkeypatch.setenv("DADDY_DOCTOR_WATCH_CI", "true")
    assert _process_once(archive, worker.settings)["request_id"] == "pending"
    worker.poll_merged_ci.assert_called_once()


def test_repair_requires_local_reproduction_before_asking_for_a_patch():
    repair = RepairLoop(Settings(), lambda _: (True, "all passed"), lambda _: None)
    repair.api = Mock()
    request = DoctorRequest(repo_target=MOONBOYS_REPO, problem_summary="CI regression")
    with pytest.raises(PermissionError, match="did not reproduce"):
        repair.run(Mock(), request, [], [], require_baseline_failure=True)
    repair.api.generate_json.assert_not_called()
