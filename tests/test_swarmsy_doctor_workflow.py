from __future__ import annotations

from pathlib import Path

from the_daddy.config import Settings
from the_daddy.engine import DaddyEngine
from the_daddy.swarmsy_doctor import (
    DoctorQueueConsumer,
    DoctorRepairAttempt,
    DoctorRequest,
    DoctorReviewComment,
    InMemoryDoctorArchive,
    SWARMSY_REPO,
    classify_review_comment,
    create_doctor_request_from_plain_language,
    show_recent_daddy_repairs,
)


class FakeWorker:
    def __init__(self, initial: DoctorRepairAttempt, follow_up: list[DoctorRepairAttempt] | None = None, merge_result: bool = False):
        self.initial = initial
        self.follow_up = list(follow_up or [])
        self.merge_result = merge_result
        self.fix_calls = 0

    def run_initial_repair(self, request: DoctorRequest) -> DoctorRepairAttempt:
        return self.initial

    def apply_review_comment_fixes(self, request: DoctorRequest, actionable_comments: list[DoctorReviewComment], cycle: int) -> DoctorRepairAttempt:
        self.fix_calls += 1
        if self.follow_up:
            return self.follow_up.pop(0)
        return self.initial

    def merge_pr(self, request: DoctorRequest, pr_url: str) -> bool:
        return self.merge_result


def _consumer(archive: InMemoryDoctorArchive, worker: FakeWorker, *, auto_merge: bool = False) -> DoctorQueueConsumer:
    return DoctorQueueConsumer(
        archive=archive,
        worker=worker,
        allowed_target_repos={"HODLKONG64/THEY-CALL-ME-THE-DADDY", SWARMSY_REPO},
        swarmsy_auto_merge=auto_merge,
        max_review_cycles=2,
    )


def test_plain_language_request_is_converted_to_structured_doctor_request():
    request, response = create_doctor_request_from_plain_language("Ask Daddy to fix the SWARMSY workspace upload bug.")

    assert request.status == "queued"
    assert request.problem_summary == "the SWARMSY workspace upload bug"
    assert request.repo_target == SWARMSY_REPO
    assert request.archive_id
    assert request.allowed_paths
    assert response == "Doctor request queued. You can leave this. I’ll track it in the repair archive."


def test_queued_request_is_consumed_and_enters_repair_flow():
    archive = InMemoryDoctorArchive()
    request, _ = create_doctor_request_from_plain_language("Ask Daddy to fix workspace upload bug")
    archive.upsert_request(request)

    worker = FakeWorker(
        DoctorRepairAttempt(
            validation_passed=True,
            pr_url="https://github.com/HODLKONG64/SWARMSY/pull/1",
            tests_run=["npm test -- --watch=false"],
            changed_paths=["src/upload.ts"],
        )
    )

    result = _consumer(archive, worker).process_next()

    assert result is not None
    assert result.status == "pr_opened_waiting_review"
    statuses = [item["status"] for item in result.status_timeline]
    assert statuses[0] == "queued"
    assert "running" in statuses


def test_invalid_repo_request_is_blocked_with_reason():
    archive = InMemoryDoctorArchive()
    request, _ = create_doctor_request_from_plain_language(
        "Ask Daddy to fix private infra",
        repo_target="acme/private-repo",
    )
    archive.upsert_request(request)

    worker = FakeWorker(DoctorRepairAttempt(validation_passed=True, pr_url="https://example.test/pr/1"))
    result = _consumer(archive, worker).process_next()

    assert result is not None
    assert result.status == "blocked_needs_human_permission"
    assert "not allowlisted" in result.final_reason


def test_review_comment_classification_handles_actionable_stale_and_human_gate():
    actionable = DoctorReviewComment(comment_id="1", body="This fails tests and must be fixed", state="open")
    stale = DoctorReviewComment(comment_id="2", body="stale optional nit, already fixed", state="open")
    human = DoctorReviewComment(comment_id="3", body="Requires security approval before merge", state="open")

    assert classify_review_comment(actionable) == "actionable_blocker"
    assert classify_review_comment(stale) == "stale_noise"
    assert classify_review_comment(human) == "needs_human_approval"


def test_actionable_review_comment_triggers_additional_patch_cycle():
    archive = InMemoryDoctorArchive()
    request, _ = create_doctor_request_from_plain_language("Ask Daddy to fix workspace upload bug")
    archive.upsert_request(request)

    first_attempt = DoctorRepairAttempt(
        validation_passed=True,
        pr_url="https://github.com/HODLKONG64/SWARMSY/pull/2",
        tests_run=["npm run typecheck"],
        changed_paths=["src/upload.ts"],
        review_comments=[DoctorReviewComment(comment_id="a", body="must fix lint failure", state="open")],
    )
    second_attempt = DoctorRepairAttempt(
        validation_passed=True,
        pr_url="https://github.com/HODLKONG64/SWARMSY/pull/2",
        tests_run=["npm run check:hygiene"],
        changed_paths=["src/upload.ts"],
        review_comments=[],
    )
    worker = FakeWorker(first_attempt, follow_up=[second_attempt])

    result = _consumer(archive, worker).process_next()

    assert result is not None
    assert result.status == "pr_opened_waiting_review"
    assert worker.fix_calls == 1


def test_stale_noise_review_comment_does_not_block_forever():
    archive = InMemoryDoctorArchive()
    request, _ = create_doctor_request_from_plain_language("Ask Daddy to fix stale warning")
    archive.upsert_request(request)

    worker = FakeWorker(
        DoctorRepairAttempt(
            validation_passed=True,
            pr_url="https://github.com/HODLKONG64/SWARMSY/pull/3",
            changed_paths=["src/upload.ts"],
            review_comments=[DoctorReviewComment(comment_id="s", body="stale optional nit", state="open")],
        )
    )

    result = _consumer(archive, worker).process_next()
    assert result is not None
    assert result.status == "pr_opened_waiting_review"


def test_request_reaches_final_archived_status_and_is_queryable():
    archive = InMemoryDoctorArchive()
    request, _ = create_doctor_request_from_plain_language("Ask Daddy to fix upload bug")
    archive.upsert_request(request)

    worker = FakeWorker(
        DoctorRepairAttempt(
            validation_passed=True,
            pr_url="https://github.com/HODLKONG64/SWARMSY/pull/4",
            changed_paths=["src/upload.ts"],
        ),
        merge_result=True,
    )

    result = _consumer(archive, worker, auto_merge=True).process_next()
    rows = show_recent_daddy_repairs(archive, limit=5)

    assert result is not None
    assert result.status == "merged"
    assert rows
    assert rows[0]["archive_id"] == result.archive_id
    assert rows[0]["status"] in {"merged", "pr_opened_waiting_review", "blocked_needs_human_permission", "failed_with_reason"}


def test_daddy_self_repair_path_still_runs():
    settings = Settings(
        target_root=Path("."),
        command="python -c \"print('ok')\"",
        enable_self_evolution=False,
        enable_architecture_lane=False,
    )
    engine = DaddyEngine(settings)
    record = engine.run()
    assert record is not None


def test_swarmsy_mode_cannot_target_non_swarmsy_repo_even_if_allowlisted():
    archive = InMemoryDoctorArchive()
    request = DoctorRequest(
        problem_summary="wrong target",
        repo_target="HODLKONG64/THEY-CALL-ME-THE-DADDY",
        source="swarmsy",
        allowed_paths=["src/"],
    )
    request.status_timeline = [{"status": "queued", "at": request.created_at, "reason": "test"}]
    archive.upsert_request(request)

    worker = FakeWorker(DoctorRepairAttempt(validation_passed=True, pr_url="https://example.test/pr/5"))
    result = _consumer(archive, worker).process_next()

    assert result is not None
    assert result.status == "blocked_needs_human_permission"
    assert "can target only HODLKONG64/SWARMSY" in result.final_reason


def test_failed_repair_has_terminal_failure_status_not_silent_wait():
    archive = InMemoryDoctorArchive()
    request, _ = create_doctor_request_from_plain_language("Ask Daddy to fix failing check")
    archive.upsert_request(request)

    worker = FakeWorker(
        DoctorRepairAttempt(
            validation_passed=False,
            reason="Validation command failed",
            changed_paths=["src/upload.ts"],
            pr_url="https://github.com/HODLKONG64/SWARMSY/pull/6",
        )
    )
    result = _consumer(archive, worker).process_next()

    assert result is not None
    assert result.status == "failed_with_reason"
    assert result.status in {"merged", "pr_opened_waiting_review", "blocked_needs_human_permission", "failed_with_reason"}
