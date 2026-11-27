from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from the_daddy.config import Settings
from the_daddy.doctor_repair import DoctorWorkspace
from the_daddy.doctor_worker import GitHubDoctorWorker
from the_daddy.swarmsy_doctor import DoctorRequest, JsonDoctorArchive, MOONBOYS_REPO, WikiLinkRepair


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
    source = ('<!-- <a href="/wiki/Foo_Bar.html">comment</a> -->'
              '<a title="href=\'/wiki/Foo_Bar.html\'" HREF = "/wiki/Foo_Bar.html">link</a>'
              '<script>let text = \'<a href="/wiki/Foo_Bar.html">text</a>\';</script>')
    page.write_text(source)
    work.git("add", "wiki")
    work.commit("wiki fixture")
    work.apply(request, work.wiki_link_edits(repair))
    assert page.read_text() == source.replace('HREF = "/wiki/Foo_Bar.html"', 'HREF = "/wiki/foo-bar.html"')
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
    with pytest.raises(PermissionError):
        worker.merge_approved_website_pr(request, base, pr)
    assert worker.merge_approved_website_pr(request, head, pr) == ("", "")
    worker._api.assert_not_called()
    worker._ci_review.return_value = (True, [])
    assert worker.merge_approved_website_pr(request, head, pr)[0] == "merged"
    worker._api.assert_called_once_with("PUT", "pulls/12/merge", {"sha": head, "merge_method": "squash"})
