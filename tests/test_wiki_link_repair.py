from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from the_daddy.config import Settings
from the_daddy.doctor_repair import DoctorWorkspace
from the_daddy.doctor_worker import GitHubDoctorWorker
from the_daddy.swarmsy_doctor import DoctorEdit, DoctorRequest, JsonDoctorArchive, MOONBOYS_REPO, WikiLinkRepair


def test_wiki_request_changes_only_the_exact_anchor(tmp_path: Path):
    work = DoctorWorkspace(tmp_path, Settings())
    work.git("init")
    repair = WikiLinkRepair(page="wiki/index.html", old="/wiki/Foo_Bar.html", new="/wiki/foo-bar.html")
    request = DoctorRequest(source="daddy", request_id="support-1-2", expected_base_sha="a" * 40,
                            repo_target=MOONBOYS_REPO, problem_summary="Fix link",
                            allowed_paths=[repair.page], wiki_link=repair)
    (tmp_path / "wiki").mkdir()
    page = tmp_path / repair.page
    target = tmp_path / repair.new[1:]
    target.write_text("Evidence")
    opening = '<a title="href=\'/wiki/Foo_Bar.html\'" HREF = "/wiki/Foo_Bar.html">'
    source = ('<!-- <a href="/wiki/Foo_Bar.html">comment</a> -->\n'
              f'{opening}first link</a>\n{opening}second link</a>'
              '<script>let text = \'<a href="/wiki/Foo_Bar.html">text</a>\';</script>')
    page.write_bytes(source.encode())
    work.git("add", "wiki")
    work.commit("wiki fixture")
    work.apply(request, work.wiki_link_edits(repair))
    assert page.read_bytes().decode() == source.replace('HREF = "/wiki/Foo_Bar.html"', 'HREF = "/wiki/foo-bar.html"')
    with pytest.raises(ValueError, match="changed since"):
        target.unlink()
        work.wiki_link_edits(repair)


def test_wiki_link_cannot_point_to_unrelated_page():
    with pytest.raises(ValidationError, match="normalize the spelling"):
        WikiLinkRepair(page="wiki/index.html", old="/wiki/Foo.html", new="/wiki/unrelated.html")


def test_doctor_merges_only_the_approved_website_head_with_clean_checks(tmp_path: Path):
    settings = Settings(github_repo=MOONBOYS_REPO, allowed_target_repos=frozenset({MOONBOYS_REPO}))
    worker = GitHubDoctorWorker(settings, JsonDoctorArchive(tmp_path / "archive.json"),
                                validation_image="fixture", validation_command="true", required_checks={"tests"})
    head = "a" * 40
    base = "b" * 40
    request = DoctorRequest(repo_target=MOONBOYS_REPO, problem_summary="Fix link", head_sha=head,
                            source="daddy", request_id="support-1-2", base_sha=base,
                            pr_number=12, review_request_id=1)
    pr = {
        "head": {"repo": {"full_name": MOONBOYS_REPO}, "sha": head, "ref": worker._branch(request)},
        "base": {"repo": {"full_name": MOONBOYS_REPO}, "sha": base, "ref": "main"},
        "state": "open", "draft": False, "mergeable": True, "mergeable_state": "clean",
    }
    worker._api = Mock(return_value={"merged": True})
    worker._ci_review = Mock(return_value=(False, []))
    worker._list = Mock(return_value=[])
    with pytest.raises(PermissionError):
        worker.merge_approved_website_pr(request, base, pr)
    assert worker.merge_approved_website_pr(request, head, pr) == ("", "")
    worker._api.assert_not_called()
    worker._ci_review.return_value = (True, [])
    assert worker.merge_approved_website_pr(request, head, pr) == ("", "")
    worker._api.assert_not_called()
    worker.telegram.enabled = True
    worker.telegram.decision = Mock(return_value="approved")
    worker._codex_review = Mock(return_value=("approved", []))
    worker._repo = Mock(return_value=("main", base))
    worker._api.return_value = pr
    assert worker.ci_workflow == "full-linux-test-suite.yml"
    assert worker.merge_approved_website_pr(request, head, pr) == ("", "")
    worker._api.assert_called_once_with("GET", "pulls/12")
    worker._api.reset_mock()
    worker._list.return_value = [{"id": 1, "head_sha": head, "head_branch": worker._branch(request),
                                  "event": "workflow_dispatch", "status": "completed", "conclusion": "success"}]
    worker._api.side_effect = [pr, {"merged": True}]
    assert worker.merge_approved_website_pr(request, head, pr)[0] == "merged"
    assert worker._api.call_count == 2
    worker._api.assert_called_with("PUT", "pulls/12/merge", {"sha": head, "merge_method": "squash"})


def test_website_requires_a_github_actions_runtime_image_check(tmp_path: Path):
    settings = Settings(github_repo=MOONBOYS_REPO, allowed_target_repos=frozenset({MOONBOYS_REPO}))
    worker = GitHubDoctorWorker(settings, JsonDoctorArchive(tmp_path / "archive.json"),
                                validation_image="fixture", validation_command="true", required_checks=set())
    head = "a" * 40
    check = {"name": "Runtime Image Policy", "head_sha": head, "conclusion": "success"}
    worker._list = Mock(side_effect=[
        [{**check, "app": {"slug": "third-party"}}], [{"context": check["name"], "state": "success"}],
        [{**check, "app": {"slug": "github-actions"}}], [],
    ])
    assert worker._ci_review(head) == (False, [])
    assert worker._ci_review(head) == (True, [])


@pytest.mark.parametrize("worker_edit", [False, True])
def test_website_deploy_tracking_matches_the_production_workflow(tmp_path: Path, worker_edit):
    settings = Settings(github_repo=MOONBOYS_REPO, allowed_target_repos=frozenset({MOONBOYS_REPO}))
    archive = JsonDoctorArchive(tmp_path / "archive.json")
    worker = GitHubDoctorWorker(settings, archive, validation_image="fixture",
                                validation_command="true", required_checks=set())
    commit = "a" * 40
    path = "workers/moonboys-api/route.js" if worker_edit else "wiki/index.html"
    request = DoctorRequest(repo_target=MOONBOYS_REPO, source="daddy", request_id="support-1-2",
                            problem_summary="Fix site", pr_number=12, allowed_paths=[path],
                            learned_edits=[DoctorEdit(path=path, old="old", new="new")])
    worker._record_merge(request, commit, "main")
    common = {"id": 1, "status": "completed", "conclusion": "success"}
    if worker_edit:
        assert request.deployment_workflow == "cloudflare-pr-release.yml"
        valid = {**common, "event": "pull_request_target", "head_sha": "b" * 40,
                 "display_title": f"Cloudflare release PR #12 {commit}"}
        unrelated = {**valid, "id": 2, "display_title": f"Cloudflare validate PR #12 {commit}"}
    else:
        assert request.deployment_workflow == "pages.yml"
        valid = {**common, "event": "push", "head_sha": commit, "head_branch": "main"}
        unrelated = {**valid, "id": 2, "head_sha": "b" * 40}
    jobs = [{"name": request.deployment_job, "conclusion": "success"}]
    if worker_edit:
        def release_pages():
            yield [unrelated]
            yield [valid]
            pytest.fail("Lookup must stop at the first matching release page")
        worker._pages = Mock(return_value=release_pages())
        worker._list = Mock(return_value=jobs)
    else:
        worker._list = Mock(side_effect=[[valid, unrelated], jobs])
    worker.poll_deployment(request)
    assert request.deployment_status == "deployed"
    assert request.deployment_url.endswith("/actions/runs/1")
