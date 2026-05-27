from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field

FINAL_STATUSES = {
    "merged",
    "pr_opened_waiting_review",
    "blocked_needs_human_permission",
    "failed_with_reason",
}

SWARMSY_REPO = "HODLKONG64/SWARMSY"

_SECRET_PATH_MARKERS = (
    ".env",
    "secret",
    "secrets",
    "id_rsa",
    ".pem",
    ".key",
    "credentials",
    "token",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_path(path: str) -> str:
    value = str(path or "").replace("\\", "/").strip()
    while "//" in value:
        value = value.replace("//", "/")
    if value.startswith("./"):
        value = value[2:]
    if not value:
        return ""
    if value.startswith("/") or (len(value) >= 3 and value[1] == ":" and value[2] == "/"):
        raise ValueError(f"Absolute paths are not allowed: {path}")

    parts: list[str] = []
    for part in value.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise ValueError(f"Parent-directory traversal is not allowed: {path}")
        parts.append(part)
    return "/".join(parts)


def default_allowed_paths_for_repo(target_repo: str) -> list[str]:
    if target_repo == SWARMSY_REPO:
        return ["src/", "app/", "components/", "lib/", "tests/", "docs/", "package.json", "package-lock.json", "tsconfig.json"]
    return ["src/", "tests/", "docs/", "pyproject.toml", "README.md"]


def _extract_problem_summary(command: str) -> str:
    text = str(command or "").strip()
    lowered = text.lower()
    marker = "ask daddy to fix"
    if marker in lowered:
        start = lowered.find(marker) + len(marker)
        summary = text[start:].strip(" .!:\n")
        if summary:
            return summary
    return text or "User-requested repair"


def _extract_feature_hint(command: str) -> str:
    text = str(command or "")
    lowered = text.lower()
    for marker in ("bug in", "issue in", "on page", "in screen", "in feature"):
        start = lowered.find(marker)
        if start >= 0:
            return text[start + len(marker) :].strip(" .!:\n")
    return ""


class DoctorReviewComment(BaseModel):
    comment_id: str = ""
    author: str = ""
    body: str = ""
    state: Literal["open", "resolved"] = "open"


class DoctorRepairAttempt(BaseModel):
    validation_passed: bool = False
    pr_url: str = ""
    tests_run: list[str] = Field(default_factory=list)
    changed_paths: list[str] = Field(default_factory=list)
    review_comments: list[DoctorReviewComment] = Field(default_factory=list)
    reason: str = ""
    destructive_change: bool = False


class DoctorRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: f"doctor-{uuid.uuid4().hex[:12]}")
    archive_id: str = Field(default_factory=lambda: f"repair-{uuid.uuid4().hex[:10]}")
    source: Literal["swarmsy", "daddy"] = "swarmsy"
    problem_summary: str
    repo_target: str
    user_intent: str = "repair"
    feature_hint: str = ""
    logs: list[str] = Field(default_factory=list)
    screenshots: list[str] = Field(default_factory=list)
    failing_command: str = ""
    allowed_paths: list[str] = Field(default_factory=list)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    status: Literal[
        "queued",
        "running",
        "merged",
        "pr_opened_waiting_review",
        "blocked_needs_human_permission",
        "failed_with_reason",
    ] = "queued"
    status_timeline: list[dict[str, str]] = Field(default_factory=list)
    doctor_request_issue_url: str = ""
    swarmsy_archive_entry_url: str = ""
    swarmsy_pr_url: str = ""
    tests_run: list[str] = Field(default_factory=list)
    final_reason: str = ""
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class DoctorWorker(Protocol):
    def run_initial_repair(self, request: DoctorRequest) -> DoctorRepairAttempt:
        ...

    def apply_review_comment_fixes(
        self,
        request: DoctorRequest,
        actionable_comments: list[DoctorReviewComment],
        cycle: int,
    ) -> DoctorRepairAttempt:
        ...

    def merge_pr(self, request: DoctorRequest, pr_url: str) -> bool:
        ...


class DoctorArchive(Protocol):
    def list_queued_requests(self) -> list[DoctorRequest]:
        ...

    def upsert_request(self, request: DoctorRequest) -> None:
        ...

    def recent_requests(self, limit: int = 10) -> list[DoctorRequest]:
        ...


class JsonDoctorArchive:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[DoctorRequest]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8") or "[]")
        except json.JSONDecodeError as exc:
            print(f"Warning: ignoring corrupt Doctor archive {self.path}: {exc}", file=sys.stderr)
            return []
        if not isinstance(raw, list):
            return []
        out: list[DoctorRequest] = []
        for item in raw:
            try:
                out.append(DoctorRequest.model_validate(item))
            except Exception:
                continue
        return out

    def _save(self, items: list[DoctorRequest]) -> None:
        payload = [item.model_dump(mode="json") for item in items]
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list_queued_requests(self) -> list[DoctorRequest]:
        return [item for item in self._load() if item.status == "queued"]

    def upsert_request(self, request: DoctorRequest) -> None:
        items = self._load()
        replaced = False
        for idx, item in enumerate(items):
            if item.request_id == request.request_id:
                items[idx] = request
                replaced = True
                break
        if not replaced:
            items.append(request)
        self._save(items)

    def recent_requests(self, limit: int = 10) -> list[DoctorRequest]:
        items = self._load()
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items[: max(1, int(limit))]


class InMemoryDoctorArchive:
    def __init__(self) -> None:
        self._items: list[DoctorRequest] = []

    def list_queued_requests(self) -> list[DoctorRequest]:
        return [item for item in self._items if item.status == "queued"]

    def upsert_request(self, request: DoctorRequest) -> None:
        for idx, item in enumerate(self._items):
            if item.request_id == request.request_id:
                self._items[idx] = request
                return
        self._items.append(request)

    def recent_requests(self, limit: int = 10) -> list[DoctorRequest]:
        return sorted(self._items, key=lambda item: item.updated_at, reverse=True)[: max(1, int(limit))]


class NoopDoctorWorker:
    def run_initial_repair(self, request: DoctorRequest) -> DoctorRepairAttempt:
        return DoctorRepairAttempt(
            validation_passed=False,
            reason="No worker configured for Doctor request processing.",
            tests_run=["not_run:no_worker"],
        )

    def apply_review_comment_fixes(
        self,
        request: DoctorRequest,
        actionable_comments: list[DoctorReviewComment],
        cycle: int,
    ) -> DoctorRepairAttempt:
        return DoctorRepairAttempt(
            validation_passed=False,
            reason=f"No worker configured to address actionable comments (cycle {cycle}).",
            tests_run=["not_run:no_worker"],
        )

    def merge_pr(self, request: DoctorRequest, pr_url: str) -> bool:
        return False


def create_doctor_request_from_plain_language(
    command: str,
    *,
    repo_target: str = SWARMSY_REPO,
    user_intent: str = "repair",
    logs: list[str] | None = None,
    screenshots: list[str] | None = None,
    failing_command: str = "",
    priority: Literal["low", "normal", "high", "urgent"] = "normal",
    allowed_paths: list[str] | None = None,
) -> tuple[DoctorRequest, str]:
    request = DoctorRequest(
        source="swarmsy",
        problem_summary=_extract_problem_summary(command),
        repo_target=repo_target,
        user_intent=user_intent,
        feature_hint=_extract_feature_hint(command),
        logs=list(logs or []),
        screenshots=list(screenshots or []),
        failing_command=failing_command,
        allowed_paths=list(allowed_paths or default_allowed_paths_for_repo(repo_target)),
        priority=priority,
        status="queued",
        status_timeline=[{"status": "queued", "at": utc_now_iso(), "reason": "request_created"}],
    )
    response = "Doctor request queued. You can leave this. I’ll track it in the repair archive."
    return request, response


def _is_secret_path(path: str) -> bool:
    try:
        norm = _normalize_path(path).lower()
    except ValueError:
        return False
    return any(marker in norm for marker in _SECRET_PATH_MARKERS)


def _path_within_allowlist(path: str, allowed_paths: list[str]) -> bool:
    try:
        norm = _normalize_path(path).lower()
    except ValueError:
        return False
    for allow in allowed_paths:
        try:
            candidate = _normalize_path(allow).lower()
        except ValueError:
            continue
        if not candidate:
            continue
        if norm == candidate or norm.startswith(candidate.rstrip("/") + "/"):
            return True
    return False


def classify_review_comment(comment: DoctorReviewComment) -> Literal["actionable_blocker", "stale_noise", "needs_human_approval"]:
    body = str(comment.body or "").lower()
    if any(token in body for token in ("security approval", "human approval", "credentials", "policy override", "manual decision")):
        return "needs_human_approval"
    if any(token in body for token in ("stale", "nit", "optional", "already fixed", "resolved", "noise")):
        return "stale_noise"
    return "actionable_blocker"


def show_recent_daddy_repairs(archive: DoctorArchive, *, limit: int = 10) -> list[dict[str, str]]:
    repairs = archive.recent_requests(limit=limit)
    return [
        {
            "archive_id": item.archive_id,
            "status": item.status,
            "problem_summary": item.problem_summary,
            "repo_target": item.repo_target,
            "pr_url": item.swarmsy_pr_url,
            "updated_at": item.updated_at,
            "reason": item.final_reason,
        }
        for item in repairs
    ]


class DoctorQueueConsumer:
    def __init__(
        self,
        *,
        archive: DoctorArchive,
        worker: DoctorWorker,
        allowed_target_repos: set[str],
        swarmsy_auto_merge: bool = False,
        max_review_cycles: int = 3,
    ) -> None:
        self.archive = archive
        self.worker = worker
        self.allowed_target_repos = set(allowed_target_repos)
        self.swarmsy_auto_merge = bool(swarmsy_auto_merge)
        self.max_review_cycles = max(1, int(max_review_cycles))

    def _transition(self, request: DoctorRequest, status: str, reason: str) -> None:
        request.status = status  # type: ignore[assignment]
        request.updated_at = utc_now_iso()
        request.status_timeline.append({"status": status, "at": request.updated_at, "reason": reason})

    def _finalize(self, request: DoctorRequest, status: str, reason: str, tests_run: list[str] | None = None) -> DoctorRequest:
        self._transition(request, status, reason)
        request.final_reason = reason
        if tests_run:
            request.tests_run = list(dict.fromkeys([*request.tests_run, *tests_run]))
        self.archive.upsert_request(request)
        return request

    def _request_is_safe(self, request: DoctorRequest) -> tuple[bool, str]:
        if request.repo_target not in self.allowed_target_repos:
            return False, f"Target repo {request.repo_target} is not allowlisted."
        if request.source == "swarmsy" and request.repo_target != SWARMSY_REPO:
            return False, "SWARMSY Doctor mode can target only HODLKONG64/SWARMSY."
        if not request.allowed_paths:
            return False, "No allowed paths provided."
        for path in request.allowed_paths:
            try:
                _normalize_path(path)
            except ValueError:
                return False, f"Allowed path is unsafe: {path}"
            if _is_secret_path(path):
                return False, f"Allowed path is unsafe: {path}"
        return True, ""

    def _attempt_is_safe(self, request: DoctorRequest, attempt: DoctorRepairAttempt) -> tuple[bool, str]:
        if attempt.destructive_change:
            return False, "Destructive change flagged by worker."
        for changed in attempt.changed_paths:
            try:
                _normalize_path(changed)
            except ValueError:
                return False, f"Changed path is unsafe: {changed}"
            if _is_secret_path(changed):
                return False, f"Secret file path touched: {changed}"
            if not _path_within_allowlist(changed, request.allowed_paths):
                return False, f"Changed path outside allowed scope: {changed}"
        return True, ""

    def process_next(self) -> DoctorRequest | None:
        queued = self.archive.list_queued_requests()
        if not queued:
            return None
        return self.process_request(queued[0])

    def process_request(self, request: DoctorRequest) -> DoctorRequest:
        self._transition(request, "running", "queue_consumer_started")
        self.archive.upsert_request(request)

        safe, reason = self._request_is_safe(request)
        if not safe:
            return self._finalize(request, "blocked_needs_human_permission", reason)

        attempt = self.worker.run_initial_repair(request)
        request.tests_run = list(dict.fromkeys([*request.tests_run, *attempt.tests_run]))
        request.swarmsy_pr_url = attempt.pr_url or request.swarmsy_pr_url

        safe_attempt, safe_reason = self._attempt_is_safe(request, attempt)
        if not safe_attempt:
            return self._finalize(request, "blocked_needs_human_permission", safe_reason, attempt.tests_run)

        cycle = 0
        while True:
            actionable = [c for c in attempt.review_comments if c.state == "open" and classify_review_comment(c) == "actionable_blocker"]
            needs_human = [c for c in attempt.review_comments if c.state == "open" and classify_review_comment(c) == "needs_human_approval"]

            if needs_human:
                return self._finalize(
                    request,
                    "blocked_needs_human_permission",
                    "Review comments require human approval.",
                    attempt.tests_run,
                )

            if not actionable:
                break

            if cycle >= self.max_review_cycles:
                return self._finalize(
                    request,
                    "pr_opened_waiting_review",
                    "Actionable review comments remain after safety limit.",
                    attempt.tests_run,
                )

            cycle += 1
            attempt = self.worker.apply_review_comment_fixes(request, actionable, cycle)
            request.tests_run = list(dict.fromkeys([*request.tests_run, *attempt.tests_run]))
            if attempt.pr_url:
                request.swarmsy_pr_url = attempt.pr_url
            safe_attempt, safe_reason = self._attempt_is_safe(request, attempt)
            if not safe_attempt:
                return self._finalize(request, "blocked_needs_human_permission", safe_reason, attempt.tests_run)

        if not attempt.validation_passed:
            return self._finalize(
                request,
                "failed_with_reason",
                attempt.reason or "Validation failed after repair attempt.",
                attempt.tests_run,
            )

        if not request.swarmsy_pr_url:
            return self._finalize(
                request,
                "failed_with_reason",
                "Repair attempt ended without a PR URL.",
                attempt.tests_run,
            )

        should_try_merge = (
            request.repo_target == SWARMSY_REPO
            and self.swarmsy_auto_merge
            and attempt.validation_passed
        )
        if should_try_merge and self.worker.merge_pr(request, request.swarmsy_pr_url):
            return self._finalize(request, "merged", "Merged automatically after passing policy gates.", attempt.tests_run)

        return self._finalize(request, "pr_opened_waiting_review", "PR opened and waiting for review/merge policy.", attempt.tests_run)
