from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Mapping

from pydantic import BaseModel, Field


DoctorRequestStatus = Literal["queued", "waiting_for_doctor", "pr_opened", "failed", "blocked"]
DoctorRequestPriority = Literal["low", "normal", "high", "critical"]
DOCTOR_REQUEST_STATUSES: tuple[DoctorRequestStatus, ...] = (
    "queued",
    "waiting_for_doctor",
    "pr_opened",
    "failed",
    "blocked",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DoctorRequestResponse(BaseModel):
    doctor_run_id: str | None = None
    branch: str | None = None
    pr_url: str | None = None
    result: str | None = None


class DoctorRequest(BaseModel):
    id: str = Field(min_length=1)
    source_repo: str = Field(min_length=1)
    target_repo: str = Field(min_length=1)
    status: DoctorRequestStatus = "queued"
    priority: DoctorRequestPriority = "normal"
    problem_summary: str = ""
    requested_fix: str = ""
    failing_commands: list[str] = Field(default_factory=list)
    known_logs: list[str] = Field(default_factory=list)
    allowed_paths: list[str] = Field(default_factory=list)
    blocked_paths: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)
    response: DoctorRequestResponse = Field(default_factory=DoctorRequestResponse)


def ensure_doctor_request(payload: Mapping[str, Any] | DoctorRequest) -> DoctorRequest:
    if isinstance(payload, DoctorRequest):
        return payload
    return DoctorRequest.model_validate(dict(payload))


def mark_doctor_request_status(
    request: Mapping[str, Any] | DoctorRequest,
    status: DoctorRequestStatus,
    *,
    doctor_run_id: str | None = None,
    branch: str | None = None,
    pr_url: str | None = None,
    result: str | None = None,
) -> DoctorRequest:
    current = ensure_doctor_request(request)
    response = current.response.model_copy(
        update={
            "doctor_run_id": doctor_run_id if doctor_run_id is not None else current.response.doctor_run_id,
            "branch": branch if branch is not None else current.response.branch,
            "pr_url": pr_url if pr_url is not None else current.response.pr_url,
            "result": result if result is not None else current.response.result,
        }
    )
    return current.model_copy(update={"status": status, "updated_at": _utc_now(), "response": response})
