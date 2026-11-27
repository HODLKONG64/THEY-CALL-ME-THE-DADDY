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



def test_urgent_arrivals_cannot_inherit_old_slot_ahead_of_review(tmp_path):
    archive = JsonDoctorArchive(tmp_path / "queue.json")
    archive._save([
        request(request_id="old-normal", updated_at="2020-01-01T00:00:00Z"),
        request(request_id="review", status="pr_opened_waiting_review", updated_at="2020-01-02T00:00:00Z"),
        request(request_id="deploy", status="merged", deployment_status="pending",
                updated_at="2020-01-03T00:00:00Z"),
    ])
    # Model the one-request-per-pass consumer, with a fresh urgent repair
    # before every pass. None may jump over a waiting in-flight poll.
    processed = []
    for i in range(3):
        archive.upsert_request(request(request_id=f"urgent-{i}", priority="urgent",
                                       updated_at=f"2020-02-0{i+1}T00:00:00Z"))
        selected = archive.active_requests(REPO)[0]
        processed.append(selected.request_id)
        if selected.status == "merged":
            selected.deployment_status = "deployed"
        else:
            selected.status = "failed_with_reason"
        archive.upsert_request(selected)
    assert processed == ["old-normal", "review", "deploy"]
    assert all(item.priority == "urgent" for item in archive.active_requests(REPO))


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

def test_r2_destination_change_reexports_and_isolates_cached_lessons(tmp_path, monkeypatch):
    monkeypatch.setenv("DADDY_DOCTOR_INTELLIGENCE_BUCKET", "doctor-first")
    monkeypatch.setenv("DADDY_DOCTOR_INTELLIGENCE_R2_ACCESS_KEY_ID", "test-access")
    monkeypatch.setenv("DADDY_DOCTOR_INTELLIGENCE_R2_SECRET_ACCESS_KEY", "test-secret")
    settings = Settings(r2_bucket="legacy", r2_endpoint_url="https://account.r2.cloudflarestorage.com")
    index = HistoryIndex(tmp_path / "history.sqlite3", settings)
    archive = JsonDoctorArchive(tmp_path / "queue.json")
    archive.upsert_request(request(request_id="local", status="merged"))
    remote_archive = JsonDoctorArchive(tmp_path / "remote.json")
    remote_archive.upsert_request(request(request_id="remote-only", status="failed_with_reason"))
    remote_index = HistoryIndex(tmp_path / "remote.sqlite3", settings)
    first = R2Stub()
    SharedLessons(remote_index, settings, client=first).sync(remote_archive, REPO, (REPO,))
    assert SharedLessons(index, settings, client=first).sync(archive, REPO, (REPO,)) == {
        "uploaded": 1, "downloaded": 1}
    assert len(shared_search(index, settings, request(), (REPO,))) == 2

    # Preserve the local index but switch to an empty bucket.
    monkeypatch.setenv("DADDY_DOCTOR_INTELLIGENCE_BUCKET", "doctor-second")
    second = R2Stub()
    assert shared_search(index, settings, request(), (REPO,)) == []
    assert SharedLessons(index, settings, client=second).sync(archive, REPO, (REPO,))["uploaded"] == 1
    assert len(second.objects) == 1
    assert len(shared_search(index, settings, request(), (REPO,))) == 1
    assert SharedLessons(index, settings, client=second).sync(archive, REPO, (REPO,))["uploaded"] == 0

    # The same bucket name under a different account is a different destination.
    other_settings = settings.model_copy(update={"r2_endpoint_url": "https://other.r2.cloudflarestorage.com"})
    third = R2Stub()
    assert shared_search(index, other_settings, request(), (REPO,)) == []
    assert SharedLessons(index, other_settings, client=third).sync(archive, REPO, (REPO,))["uploaded"] == 1
    assert len(third.objects) == 1

    # Equivalent endpoint spelling and credential rotation preserve checkpoints.
    equivalent = settings.model_copy(update={"r2_endpoint_url": "https://account.r2.cloudflarestorage.com:443/"})
    monkeypatch.setenv("DADDY_DOCTOR_INTELLIGENCE_R2_SECRET_ACCESS_KEY", "rotated-secret")
    assert SharedLessons(index, equivalent, client=second).sync(archive, REPO, (REPO,))["uploaded"] == 0

    # Switching back must recover only the first destination's cache.
    monkeypatch.setenv("DADDY_DOCTOR_INTELLIGENCE_BUCKET", "doctor-first")
    assert len(shared_search(index, settings, request(), (REPO,))) == 2

def test_r2_destination_change_does_not_inherit_import_cursor(tmp_path, monkeypatch):
    monkeypatch.setenv("DADDY_DOCTOR_INTELLIGENCE_BUCKET", "doctor-first")
    monkeypatch.setenv("DADDY_DOCTOR_INTELLIGENCE_R2_ACCESS_KEY_ID", "test-access")
    monkeypatch.setenv("DADDY_DOCTOR_INTELLIGENCE_R2_SECRET_ACCESS_KEY", "test-secret")
    settings = Settings(r2_bucket="legacy", r2_endpoint_url="https://account.r2.cloudflarestorage.com")
    index = HistoryIndex(tmp_path / "history.sqlite3", settings)
    archive = JsonDoctorArchive(tmp_path / "queue.json")

    class PagedR2(R2Stub):
        def __init__(self):
            super().__init__()
            self.starts = []

        def list_objects_v2(self, **kwargs):
            self.starts.append(kwargs.get("StartAfter", ""))
            return super().list_objects_v2(**kwargs)

    first = PagedR2()
    from the_daddy.doctor_shared_lessons import PREFIX
    # Oversized objects are skipped, but still advance the import cursor.
    for i in range(30):
        first.objects[f"{PREFIX}{REPO}/{i:02d}.json"] = b"x" * 17000
    one = SharedLessons(index, settings, client=first)
    one.sync(archive, REPO, (REPO,))
    one.sync(archive, REPO, (REPO,))
    assert first.starts == ["", f"{PREFIX}{REPO}/24.json"]

    # Leave a nonempty cursor on the original destination.
    one.sync(archive, REPO, (REPO,))
    monkeypatch.setenv("DADDY_DOCTOR_INTELLIGENCE_BUCKET", "doctor-second")
    second = PagedR2()
    SharedLessons(index, settings, client=second).sync(archive, REPO, (REPO,))
    assert second.starts == [""]
    monkeypatch.setenv("DADDY_DOCTOR_INTELLIGENCE_BUCKET", "doctor-first")
    one.sync(archive, REPO, (REPO,))
    assert first.starts[-1] == f"{PREFIX}{REPO}/24.json"


def test_shared_scope_independent_of_history(monkeypatch):
    from the_daddy.doctor_history import shared_repo_scope
    monkeypatch.setenv("DADDY_DOCTOR_HISTORY_REPOS", REPO)
    monkeypatch.delenv("DADDY_DOCTOR_SHARED_REPOS", raising=False)
    assert shared_repo_scope(REPO) == (REPO,)
    monkeypatch.setenv("DADDY_DOCTOR_SHARED_REPOS", OTHER)
    assert shared_repo_scope(REPO) == (OTHER, REPO)
    assert repo_scope(REPO, REPO) == (REPO,)
    monkeypatch.setenv("DADDY_DOCTOR_SHARED_REPOS", "")
    assert shared_repo_scope(REPO) == (REPO,)
    monkeypatch.setenv("DADDY_DOCTOR_SHARED_REPOS", "https://invalid.test/repo")
    with pytest.raises(ValueError):
        shared_repo_scope(REPO)


def test_intelligence_report_is_aggregate_and_deduplicated(tmp_path):
    from the_daddy.doctor_diagnostics import report
    archive = JsonDoctorArchive(tmp_path / "queue.json")
    index = HistoryIndex(tmp_path / "history.sqlite3", Settings())
    archive._save([
        request(request_id="one", status="merged", problem_summary="Private worker timeout",
                post_merge_ci="passed", deployment_status="failed"),
        request(request_id="two", status="failed_with_reason", problem_summary="Worker timeout private"),
        request(request_id="other", repo_target=OTHER, status="merged"),
    ])
    data = report(archive, index, REPO, (REPO,))
    assert data["requests"] == 2
    assert data["merge_fraction_of_terminal_cases"] == 0.5
    assert data["deployment_jobs"] == {"failed": 1}
    assert data["repeated_normalized_problem_groups"] == 1
    assert data["cases_per_repeated_group"] == [2]
    assert data["history_coverage"][0]["initial_scan_checkpointed"] is False
    assert "Private worker timeout" not in json.dumps(data)


def test_history_enriches_merged_pr_without_replay(tmp_path):
    index = HistoryIndex(tmp_path / "history.sqlite3", Settings())
    row = {"number": 9, "title": "Worker upload timeout", "body": "", "state": "closed",
           "pull_request": {}, "updated_at": "2026-11-01T00:00:00Z"}
    def api(repo, endpoint):
        if endpoint.startswith("issues?"):
            return [row]
        if endpoint == "pulls/9":
            return {"merged": True, "merge_commit_sha": "a"*40, "head": {"sha": "b"*40}}
        if endpoint.startswith("pulls/9/files"):
            return [{"filename": "src/example.py", "patch": "+GITHUB_TOKEN=ghp_abcdefghijklmnopqrst"}]
        if endpoint.startswith("pulls/9/comments"):
            return [{"path": "src/example.py", "body": "Handle timeout"}]
        return []
    index.sync_page(REPO, api)
    result = index.search(request(), (REPO,), api)[0]
    assert result["merge_sha"] == "a"*40
    assert result["outcome"] == "merged_not_production_verified"
    assert result["inline_review_notes"][0]["body"] == "Handle timeout"
    assert "ghp_abcdefghijklmnopqrst" not in json.dumps(result)
    assert "learned_edits" not in result


def test_distillation_filters_noise_preserves_claims_and_is_incremental(tmp_path):
    from the_daddy.doctor_distillation import distill_pending, retrieve, coverage
    index = HistoryIndex(tmp_path / "history.sqlite3", Settings())
    row = {"number": 19, "title": "Fix Worker upload timeout", "state": "closed",
           "pull_request": {}, "updated_at": "2026-11-01T00:00:00Z",
           "body": "Thanks!\n@codex review\nRoot cause: Worker upload timeout\n"
                   "Fix: Retry API request\nFix: Retry API request\n"
                   "Verification: Tests pass\n<!-- internal template -->"}
    calls = []
    def api(repo, endpoint):
        calls.append(endpoint)
        if endpoint.startswith("issues?"):
            return [row]
        if endpoint == "pulls/19":
            return {"merged": True, "merge_commit_sha": "a"*40, "head": {"sha": "b"*40}}
        if endpoint.startswith("pulls/19/files"):
            return [{"filename": "src/example.py", "patch": "+do_not_send_raw_patch"}]
        if endpoint.startswith("pulls/19/comments"):
            return [{"body": "Useful?\nHandle API timeout\nHandle API timeout"}]
        if endpoint.startswith("commits/"):
            return {"check_runs": [{"head_sha": "a"*40, "name": "tests", "conclusion": "success"},
                                   {"head_sha": "c"*40, "name": "wrong head", "conclusion": "success"}]}
        return [{"body": "Thanks!\n@codex review"}]
    index.sync_page(REPO, api)
    result = distill_pending(index, REPO, api)
    assert result["processed"] == 1
    assert result["evidence_retry"] == 0
    before = len(calls)
    assert distill_pending(index, REPO, api)["processed"] == 0
    records = retrieve(index, request(problem_summary="Worker upload timeout"), (REPO,))
    assert len(calls) == before
    item = records[0]
    assert item["reported_root_cause"] == ["Worker upload timeout"]
    assert item["reported_solution"] == ["Retry API request"]
    assert item["status"] == "merged_not_production_verified"
    assert item["observed_merge_checks"] == [{"name": "tests", "conclusion": "success"}]
    assert item["affected_paths"] == ["src/example.py"]
    assert item["review_findings_unverified"] == ["Handle API timeout"]
    assert "do_not_send_raw_patch" not in json.dumps(item)
    assert "@codex review" not in json.dumps(item)
    assert coverage(index, (REPO,))[0]["distilled_current"] == 1
    # Source changes invalidate prior conclusions until the next successful enrichment.
    row["body"] = "Problem: Worker upload timeout\nFailure: Retry did not work"
    row["updated_at"] = "2026-11-02T00:00:00Z"
    index.sync_page(REPO, api)
    item = retrieve(index, request(problem_summary="Worker upload timeout"), (REPO,))[0]
    assert item["status"] == "closed_unverified"
    assert "merge_sha" not in item
    assert coverage(index, (REPO,))[0]["stale_revision"] == 1
    assert distill_pending(index, REPO, api)["processed"] == 1


def test_distillation_retries_without_claiming_success_and_keeps_art_metadata(tmp_path):
    from the_daddy.doctor_distillation import distill_pending, retrieve, coverage
    index = HistoryIndex(tmp_path / "history.sqlite3", Settings())
    records = [
        {"number": 1, "title": "New graffiti artwork", "body": "Thanks!", "state": "closed",
         "updated_at": "2026-11-01T00:00:00Z"},
        {"number": 2, "title": "Fix API failure", "body": "", "state": "closed", "pull_request": {},
         "updated_at": "2026-11-01T00:00:00Z"},
    ]
    index.sync_page(REPO, lambda repo, endpoint: records)
    calls = []
    def failing_api(repo, endpoint):
        calls.append(endpoint)
        raise RuntimeError("temporary failure")
    result = distill_pending(index, REPO, failing_api)
    assert result == {"processed": 2, "cached": 0, "evidence_retry": 1}
    assert calls == ["pulls/2"]
    assert retrieve(index, request(problem_summary="API failure"), (REPO,))[0]["status"] == "closed_unverified"
    assert distill_pending(index, REPO, failing_api)["processed"] == 0
    assert coverage(index, (REPO,))[0]["distilled_current"] == 1


def test_distillation_context_budget_and_duplicate_provenance():
    from the_daddy.doctor_distillation import budget_evidence
    records = [{"repo": REPO, "number": n, "title": "Worker upload timeout",
                "similarity": 0.8, "status": "closed_unverified",
                "technical_notes": ["API timeout " * 300], "patch_excerpts": ["raw patch"]}
               for n in range(1, 10)]
    records.insert(0, dict(records[0]))
    result = budget_evidence(records, Settings(), max_bytes=2000)
    assert result
    assert len(result) <= 5
    assert len(json.dumps(result, ensure_ascii=True).encode()) <= 2000
    assert len({r["number"] for r in result}) == len(result)
    assert all("patch_excerpts" not in r for r in result)
