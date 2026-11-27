from pathlib import Path

import pytest
from pydantic import ValidationError

from the_daddy.config import Settings
from the_daddy.doctor_repair import DoctorWorkspace
from the_daddy.swarmsy_doctor import DoctorRequest, MOONBOYS_REPO, WikiLinkRepair


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
