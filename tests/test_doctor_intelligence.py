from __future__ import annotations

import io
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from the_daddy.config import Settings
from the_daddy.doctor_history import HistoryIndex, local_lessons, repo_scope
from the_daddy.doctor_shared_lessons import SharedLessons, shared_search
from the_daddy.doctor_worker import GitHubDoctorWorker
from the_daddy.swarmsy_doctor import DoctorRequest, DoctorEdit, JsonDoctorArchive

REPO = "hodlkong64/they-call-me-the-daddy"
OTHER = "crypto-moonboys/crypto-moonboys.github.io"


def request(**kwargs):
    return DoctorRequest(**({"problem_summary": "Worker upload timeout",
                            "repo_target": REPO, "source": "daddy",
                            "allowed_paths": ["src/"]} | kwargs))


def test_history_scope_is_explicit_and_cannot_add_write_permission():
    assert repo_scope(OTHER, REPO) == (OTHER, REPO)
    with pytest.raises(ValueError):
        repo_scope("https://evil.test/foo", REPO)


def test_exact_replay_requires_attestation_and_scope_and_reads_all_records(tmp_path):
    archive = JsonDoctorArchive(tmp_path / "queue.json")
    candidate = request(request_id="old", status="merged", head_sha="a"*40, merge_sha="b"*40,
                        updated_at="2020-01-01T00:00:00Z",
                        learned_edits=[DoctorEdit(path="src/example.py", old="a", new="b")])
    archive._save([candidate, *[request(request_id=f"new-{i}", problem_summary="unrelated",
                                      status="failed_with_reason") for i in range(110)]])
    settings = Settings(github_repo=REPO, allowed_target_repos=frozenset({REPO}))
    worker = GitHubDoctorWorker(settings, archive, validation_image="test",
                               validation_command="python -m pytest", required_checks=set())
    assert worker._memory(request()) == candidate.learned_edits
    assert not worker._memory(request(allowed_paths=["tests/"]))
    candidate.deployment_status = "failed"
    archive.upsert_request(candidate)
    assert not worker._memory(request())
    candidate.deployment_status = "unconfigured"
    candidate.head_sha = ""
    archive.upsert_request(candidate)
    assert not worker._memory(request())


def test_related_failed_repairs_are_advisory_and_secrets_are_redacted(tmp_path):
    archive = JsonDoctorArchive(tmp_path / "queue.json")
    secret = "sk-test-abcdefghijklmnop1234567890"
    archive.upsert_request(request(status="failed_with_reason", problem_summary="Upload worker timeout again",
                                   final_reason=f"OPENAI_API_KEY={secret}"))
    archive.upsert_request(request(repo_target=OTHER, status="merged"))
    lessons = local_lessons(request(), archive, Settings())
    assert len(lessons) == 1 and lessons[0]["outcome"] == "failed_with_reason"
    assert secret not in json.dumps(lessons)


def test_history_resume_dedup_failure_and_merge_provenance(tmp_path):
    index = HistoryIndex(tmp_path / "history.sqlite3", Settings())
    seen = []
    row = {"number": 3, "title": "Worker upload timeout", "body": "GITHUB_TOKEN=ghp_abcdefghijklmnopqrst",
           "state": "closed", "pull_request": {}, "updated_at": "2026-11-01T00:00:00Z"}
    def api(repo, endpoint):
        seen.append(endpoint)
        if endpoint.startswith("issues?"):
            page = parse_qs(urlsplit(endpoint).query)["page"][0]
            if page == "1":
                return [dict(row, number=n) for n in range(1, 101)]
            return [row]
        if endpoint.startswith("pulls/") and endpoint.count("/") == 1:
            return {"merged": False}
        return []
    assert index.sync_page(REPO, api)["next_page"] == 2
    with pytest.raises(RuntimeError):
        index.sync_page(REPO, lambda *_: (_ for _ in ()).throw(RuntimeError("offline")))
    assert index.sync_page(REPO, api)["cycle_complete"]
    assert "page=2" in seen[1]
    db = index.connect()
    try:
        assert db.execute("select count(*) from history").fetchone()[0] == 100
    finally:
        db.close()
    records = index.search(request(), (REPO,), api)
    assert records and all(row["outcome"] == "closed_not_verified" for row in records)
    assert "ghp_abcdefghijklmnopqrst" not in json.dumps(records)
    assert index.path.stat().st_mode & 0o777 == 0o600


def test_priority_does_not_starve_existing_review(tmp_path):
    archive = JsonDoctorArchive(tmp_path / "queue.json")
    archive._save([
        request(request_id="review", status="pr_opened_waiting_review", updated_at="2020-01-01T00:00:00Z"),
        request(request_id="normal", updated_at="2020-01-02T00:00:00Z"),
        request(request_id="urgent", priority="urgent", updated_at="2020-01-03T00:00:00Z"),
    ])
    assert [item.request_id for item in archive.active_requests(REPO)] == ["review", "urgent", "normal"]


class R2Stub:
    def __init__(self):
        self.objects = {}
    def put_object(self, *, Bucket, Key, Body, ContentType):
        self.objects[Key] = Body
    def list_objects_v2(self, *, Bucket, Prefix, MaxKeys, StartAfter=""):
        keys = sorted(k for k in self.objects if k.startswith(Prefix) and k > StartAfter)
        return {"Contents": [{"Key": key, "Size": len(self.objects[key])} for key in keys[:MaxKeys]],
                "IsTruncated": len(keys) > MaxKeys}
    def get_object(self, *, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key])}


def test_shared_memory_two_hosts_is_idempotent_and_never_transfers_edits(tmp_path, monkeypatch):
    monkeypatch.setenv("DADDY_DOCTOR_INTELLIGENCE_BUCKET", "private-doctor-intelligence")
    monkeypatch.setenv("DADDY_DOCTOR_INTELLIGENCE_R2_ACCESS_KEY_ID", "test-access")
    monkeypatch.setenv("DADDY_DOCTOR_INTELLIGENCE_R2_SECRET_ACCESS_KEY", "test-secret")
    settings = Settings(r2_bucket="legacy", r2_endpoint_url="https://account.r2.cloudflarestorage.com")
    r2 = R2Stub()
    archive = JsonDoctorArchive(tmp_path / "a.json")
    past = request(status="merged", learned_edits=[DoctorEdit(path="src/example.py", old="private", new="code")],
                   logs=["private raw log"], final_reason="Fixed worker upload timeout")
    archive.upsert_request(past)
    a = HistoryIndex(tmp_path / "a.sqlite3", settings)
    b = HistoryIndex(tmp_path / "b.sqlite3", settings)
    one, two = SharedLessons(a, settings, client=r2), SharedLessons(b, settings, client=r2)
    assert one.sync(archive, REPO, (REPO,))["uploaded"] == 1
    assert one.sync(archive, REPO, (REPO,))["uploaded"] == 0
    assert two.sync(JsonDoctorArchive(tmp_path / "b.json"), REPO, (REPO,))["downloaded"] == 1
    assert two.sync(JsonDoctorArchive(tmp_path / "b.json"), REPO, (REPO,))["downloaded"] == 0
    raw = b"".join(r2.objects.values())
    assert b"learned_edits" not in raw and b"private raw log" not in raw and b"private" not in raw
    matches = shared_search(b, settings, request(), (REPO,))
    assert len(matches) == 1 and matches[0]["outcome"] == "merged"
    assert not shared_search(b, settings, request(), (OTHER,))
