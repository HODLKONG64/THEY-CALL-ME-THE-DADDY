from __future__ import annotations

import pytest
from pydantic import ValidationError

from the_daddy.doctor_requests import DoctorRequest, ensure_doctor_request, mark_doctor_request_status


def _queued_payload() -> dict:
    return {
        "id": "doctor-request-20260527-121540",
        "source_repo": "HODLKONG64/SWARMSY",
        "target_repo": "HODLKONG64/SWARMSY",
        "status": "queued",
        "priority": "normal",
        "problem_summary": "Typecheck fails in auth path",
        "requested_fix": "Repair auth typing regression",
        "failing_commands": ["npm run typecheck"],
        "known_logs": [],
        "allowed_paths": ["src/auth/**"],
        "blocked_paths": ["infra/**"],
        "created_at": "2026-05-27T12:15:40+00:00",
        "updated_at": "2026-05-27T12:15:40+00:00",
        "response": {
            "doctor_run_id": None,
            "branch": None,
            "pr_url": None,
            "result": None,
        },
    }


def test_doctor_request_schema_validates_required_fields():
    payload = _queued_payload()
    payload.pop("id")

    with pytest.raises(ValidationError):
        ensure_doctor_request(payload)


def test_queued_request_can_transition_to_waiting_opened_failed_blocked():
    request = ensure_doctor_request(_queued_payload())
    assert isinstance(request, DoctorRequest)
    assert request.status == "queued"

    waiting = mark_doctor_request_status(request, "waiting_for_doctor", result="awaiting doctor worker")
    assert waiting.status == "waiting_for_doctor"

    opened = mark_doctor_request_status(
        waiting,
        "pr_opened",
        doctor_run_id="run-123",
        branch="doctor/fix-auth-123",
        pr_url="https://github.com/HODLKONG64/SWARMSY/pull/123",
        result="validation_passed",
    )
    assert opened.status == "pr_opened"
    assert opened.response.pr_url and opened.response.branch

    failed = mark_doctor_request_status(opened, "failed", result="validation_failed")
    assert failed.status == "failed"
    assert failed.response.result == "validation_failed"

    blocked = mark_doctor_request_status(failed, "blocked", result="blocked_by_policy")
    assert blocked.status == "blocked"
    assert blocked.response.result == "blocked_by_policy"
