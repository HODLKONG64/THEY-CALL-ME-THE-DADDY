from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field, model_validator

from .config import _normalize_repo_slug
from .runtime.redaction import sanitize_text

FINAL_STATUSES = {
    "merged",
    "blocked_needs_human_permission",
    "failed_with_reason",
}

SWARMSY_REPO = "HODLKONG64/SWARMSY"
MOONBOYS_REPO = "Crypto-Moonboys/Crypto-Moonboys.github.io"
_MOONBOYS_GAME_FILE = re.compile(r"games/[a-z0-9-]+/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-][A-Za-z0-9_.-]*\.(?:html|css|m?js)")
_MOONBOYS_PROTECTED = re.compile(
    r"auth|admin|token|secret|leaderboard|reward|score|payment|wallet|anti[-_]?cheat|session|login|ranked|payout|progression"
    r"|/(?:tests?|test-builds|vendor|node_modules|dist|build)/|\.(?:test|spec)\.m?js$",
    re.IGNORECASE,
)
_MOONBOYS_ART_FILES = {
    "moonboy-builder.html", "js/avatar-builder-core.mjs", "js/avatar-builder-test.js", "css/avatar-builder-test.css",
}


def is_moonboys_repo(repo: str) -> bool:
    return _normalize_repo_slug(repo) == _normalize_repo_slug(MOONBOYS_REPO)


def moonboys_repair_path(path: str) -> bool:
    return len(path) <= 180 and (
        path in _MOONBOYS_ART_FILES
        or bool(_MOONBOYS_GAME_FILE.fullmatch(path) and not _MOONBOYS_PROTECTED.search(path))
    )

_WIKI_PAGE = re.compile(r"wiki/[A-Za-z0-9][A-Za-z0-9_-]{0,119}\.html")


class WikiLinkRepair(BaseModel, extra="forbid"):
    page: str
    old: str
    new: str

    @model_validator(mode="after")
    def check_scope(self) -> WikiLinkRepair:
        if not _WIKI_PAGE.fullmatch(self.page) or not all(
            url.startswith("/") and _WIKI_PAGE.fullmatch(url[1:]) for url in (self.old, self.new)
        ):
            raise ValueError("Expected exact Wiki page and link paths.")
        if self.old == self.new or self.old.lower().replace("_", "-") != self.new.lower().replace("_", "-"):
            raise ValueError("Wiki link fixes can only normalize the spelling of an existing target.")
        return self

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


@contextmanager
def archive_lock(path: Path, *, blocking: bool = True):
    import fcntl

    with path.open("a", encoding="utf-8") as lock:
        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        fcntl.flock(lock, flags)
        yield


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
    if is_moonboys_repo(target_repo):
        return []  # Website jobs must supply the specific files reviewed by The Brain.
    if _normalize_repo_slug(target_repo) == _normalize_repo_slug(SWARMSY_REPO):
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


class DoctorEdit(BaseModel, extra="forbid"):
    path: str
    old: str
    new: str


class DoctorRepairAttempt(BaseModel):
    validation_passed: bool = False
    pr_url: str = ""
    tests_run: list[str] = Field(default_factory=list)
    changed_paths: list[str] = Field(default_factory=list)
    review_comments: list[DoctorReviewComment] = Field(default_factory=list)
    reason: str = ""
    destructive_change: bool = False
    review_verdict: Literal["pending", "approved", "changes_requested"] = "pending"
    merge_ready: bool = False
    merged: bool = False


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
    wiki_link: WikiLinkRepair | None = None
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
    pr_number: int = 0
    head_sha: str = ""
    base_branch: str = ""
    expected_base_sha: str = ""
    base_sha: str = ""
    merge_sha: str = ""
    deployment_status: Literal["unconfigured", "pending", "deployed", "failed"] = "unconfigured"
    deployment_workflow: str = ""
    deployment_job: str = ""
    deployment_url: str = ""
    deployment_reason: str = ""
    live_review_status: Literal["unconfigured", "pending", "passed", "needs_review", "rollback_queued"] = "unconfigured"
    live_review_reason: str = ""
    live_review_attempts: int = 0
    auto_release: bool = False
    rollback_of: str = ""
    rollback_edits: list[DoctorEdit] = Field(default_factory=list)
    pending_head_sha: str = ""
    pending_base_sha: str = ""
    pending_revalidation: bool = False
    pending_diff_digest: str = ""
    pending_codex_only: bool = False
    codex_only_head: str = ""
    codex_patch_requested_head: str = ""
    delivery_retries: int = 0
    review_cycles: int = 0
    review_request_id: int = 0
    ci_branch: str = ""
    ci_origin_pr: int = 0
    ci_follow_up: bool = False
    ci_dispatched_ref: str = ""
    ci_dispatch_status: str = ""
    post_merge_ci: Literal["unconfigured", "pending", "passed", "follow_up_queued", "needs_review"] = "unconfigured"
    post_merge_ci_url: str = ""
    post_merge_ci_reason: str = ""
    repair_log: list[dict[str, str]] = Field(default_factory=list)
    learned_edits: list[DoctorEdit] = Field(default_factory=list)
    pending_edits: list[DoctorEdit] = Field(default_factory=list)
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

    def poll_review(self, request: DoctorRequest) -> DoctorRepairAttempt:
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

    def _load(self, *, strict: bool = False) -> list[DoctorRequest]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8") or "[]")
        except json.JSONDecodeError as exc:
            if strict:
                raise ValueError("Doctor archive is corrupt. Existing data was preserved.") from exc
            print(f"Warning: unable to read Doctor archive: {exc}", file=sys.stderr)
            return []
        if isinstance(raw, dict):
            raw = raw.get("requests")
        if not isinstance(raw, list):
            if strict:
                raise ValueError("Doctor archive must contain a list of requests.")
            return []
        out: list[DoctorRequest] = []
        for item in raw:
            try:
                out.append(DoctorRequest.model_validate(item))
            except ValueError:
                if strict:
                    raise
                continue
        return out

    def _save(self, items: list[DoctorRequest]) -> None:
        payload = [item.model_dump(mode="json") for item in items]
        with tempfile.NamedTemporaryFile(dir=self.path.parent, mode="w", encoding="utf-8", delete=False) as handle:
            temporary = Path(handle.name)
            try:
                json.dump(payload, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
                handle.close()
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)

    def list_queued_requests(self) -> list[DoctorRequest]:
        return [item for item in self._load() if item.status == "queued"]

    def active_requests(self, repo: str = "", *, include_post_merge_ci: bool = True) -> list[DoctorRequest]:
        active = sorted(
            (item for item in self._load(strict=True)
             if (item.status not in FINAL_STATUSES or item.status == "merged"
                 and (item.deployment_status == "pending"
                      or item.live_review_status == "pending"
                      or include_post_merge_ci and item.post_merge_ci == "pending"))
             and (not repo or _normalize_repo_slug(item.repo_target) == _normalize_repo_slug(repo))),
            key=lambda item: item.updated_at,
        )
        # Prioritize only within consecutive queued groups. An in-flight poll is
        # a barrier: a newly queued urgent repair cannot inherit an older slot
        # ahead of that poll. Chronological order across barriers preserves progress
        # for both lanes even when new urgent requests arrive every cycle.
        priority = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
        ordered: list[DoctorRequest] = []
        queued: list[DoctorRequest] = []
        for item in active:
            if item.status == "queued":
                queued.append(item)
                continue
            ordered.extend(sorted(queued, key=lambda job: (priority[job.priority], job.updated_at)))
            queued.clear()
            ordered.append(item)
        ordered.extend(sorted(queued, key=lambda job: (priority[job.priority], job.updated_at)))
        return ordered

    def upsert_request(self, request: DoctorRequest) -> None:
        with archive_lock(self.path.with_suffix(self.path.suffix + ".lock")):
            items = {item.request_id: item for item in self._load(strict=True)}
            items[request.request_id] = request
            self._save(list(items.values()))

    def get_request(self, request_id: str) -> DoctorRequest | None:
        return next((item for item in self._load(strict=True) if item.request_id == request_id), None)

    def enqueue_once(self, request: DoctorRequest) -> DoctorRequest:
        with archive_lock(self.path.with_suffix(self.path.suffix + ".lock")):
            items = self._load(strict=True)
            existing = next((item for item in items if item.request_id == request.request_id), None)
            if existing is not None:
                return existing
            self._save([*items, request])
            return request

    def all_requests(self) -> list[DoctorRequest]:
        return self._load(strict=True)

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

    def poll_review(self, request: DoctorRequest) -> DoctorRepairAttempt:
        return self.run_initial_repair(request)


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
        norm = _normalize_path(path)
    except ValueError:
        return False
    for allow in allowed_paths:
        try:
            candidate = _normalize_path(allow)
        except ValueError:
            continue
        if not candidate:
            continue
        if norm == candidate or allow.rstrip().endswith("/") and norm.startswith(candidate + "/"):
            return True
    return False


def classify_review_comment(comment: DoctorReviewComment) -> Literal["actionable_blocker", "stale_noise", "needs_human_approval"]:
    body = str(comment.body or "").lower()
    if any(token in body for token in ("security approval", "human approval", "credential rotation", "policy override", "manual decision")):
        return "needs_human_approval"
    if body.startswith(("nit:", "optional:", "stale optional nit")) or body.strip() in {"already fixed", "resolved"}:
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
            "deployment_status": item.deployment_status,
            "deployment_url": item.deployment_url,
            "deployment_reason": item.deployment_reason,
            "live_review_status": item.live_review_status,
            "live_review_reason": item.live_review_reason,
            "post_merge_ci": item.post_merge_ci,
            "post_merge_ci_url": item.post_merge_ci_url,
            "post_merge_ci_reason": item.post_merge_ci_reason,
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
        self.allowed_target_repos = {_normalize_repo_slug(repo) for repo in allowed_target_repos}
        self.swarmsy_auto_merge = bool(swarmsy_auto_merge)
        self.max_review_cycles = max(1, int(max_review_cycles))

    def _transition(self, request: DoctorRequest, status: str, reason: str) -> None:
        if request.status != status or request.final_reason != reason:
            request.status_timeline.append({"status": status, "at": utc_now_iso(), "reason": reason})
        request.status = status  # type: ignore[assignment]
        request.updated_at = utc_now_iso()

    def _finalize(self, request: DoctorRequest, status: str, reason: str, tests_run: list[str] | None = None) -> DoctorRequest:
        self._transition(request, status, reason)
        request.final_reason = reason
        if tests_run:
            request.tests_run = list(dict.fromkeys([*request.tests_run, *tests_run]))
        self.archive.upsert_request(request)
        return request

    def _request_is_safe(self, request: DoctorRequest) -> tuple[bool, str]:
        if _normalize_repo_slug(request.repo_target) not in self.allowed_target_repos:
            return False, f"Target repo {request.repo_target} is not allowlisted."
        if request.source == "swarmsy" and _normalize_repo_slug(request.repo_target) != _normalize_repo_slug(SWARMSY_REPO):
            return False, "SWARMSY Doctor mode can target only HODLKONG64/SWARMSY."
        if not request.allowed_paths:
            return False, "No allowed paths provided."
        if request.wiki_link and (not is_moonboys_repo(request.repo_target) or request.source != "daddy"):
            return False, "Wiki link cases must use the Brain website queue."
        frontend_scope = (
            request.allowed_paths == [request.wiki_link.page] if request.wiki_link
            else 1 <= len(request.allowed_paths) <= 5 and all(map(moonboys_repair_path, request.allowed_paths))
        )
        ci_repair = (request.source == "daddy" and request.ci_origin_pr > 0
                     and bool(request.ci_branch or request.ci_follow_up))
        rollback = bool(request.rollback_of and request.request_id == request.rollback_of + "-rollback"
                        and re.fullmatch(r"support-[1-9][0-9]*-[1-9][0-9]*", request.rollback_of))
        if is_moonboys_repo(request.repo_target) and (
            not (re.fullmatch(r"support-[1-9][0-9]*-[1-9][0-9]*", request.request_id) or ci_repair or rollback)
            or not re.fullmatch(r"[a-f0-9]{40}", request.expected_base_sha)
            or not frontend_scope
        ):
            return False, "Website repairs require a Brain-approved case, exact frontend files, and a reviewed Git commit."
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
        if request.status in FINAL_STATUSES:
            return request
        safe, reason = self._request_is_safe(request)
        if not safe:
            return self._finalize(request, "blocked_needs_human_permission", reason)
        if request.status == "queued":
            self._transition(request, "running", "queue_consumer_started")
            self.archive.upsert_request(request)
        try:
            return self._process(request)
        except PermissionError as exc:
            return self._finalize(request, "blocked_needs_human_permission", sanitize_text(str(exc)))
        except Exception as exc:
            status = "failed_with_reason"
            if request.pr_number:
                status = "pr_opened_waiting_review"
            elif request.pending_head_sha:
                status = "running"
            return self._finalize(request, status, sanitize_text(str(exc)))

    def _process(self, request: DoctorRequest) -> DoctorRequest:
        if request.pr_number or request.pending_head_sha:
            attempt = self.worker.poll_review(request)
        elif request.swarmsy_pr_url:
            return self._finalize(request, "blocked_needs_human_permission", "Legacy PR has no recorded validated commit. Review it on GitHub.")
        else:
            attempt = self.worker.run_initial_repair(request)
        request.tests_run = list(dict.fromkeys([*request.tests_run, *attempt.tests_run]))
        request.swarmsy_pr_url = attempt.pr_url or request.swarmsy_pr_url

        safe_attempt, safe_reason = self._attempt_is_safe(request, attempt)
        if not safe_attempt:
            return self._finalize(request, "blocked_needs_human_permission", safe_reason, attempt.tests_run)

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

            if request.rollback_of:
                return self._finalize(request, "blocked_needs_human_permission",
                                      "The exact revert did not pass review or CI. Owner attention required.")

            if request.review_cycles >= self.max_review_cycles:
                return self._finalize(
                    request,
                    "pr_opened_waiting_review",
                    "Actionable review comments remain after safety limit.",
                    attempt.tests_run,
                )

            request.review_cycles += 1
            self.archive.upsert_request(request)
            attempt = self.worker.apply_review_comment_fixes(request, actionable, request.review_cycles)
            request.tests_run = list(dict.fromkeys([*request.tests_run, *attempt.tests_run]))
            if attempt.pr_url:
                request.swarmsy_pr_url = attempt.pr_url
            safe_attempt, safe_reason = self._attempt_is_safe(request, attempt)
            if not safe_attempt:
                return self._finalize(request, "blocked_needs_human_permission", safe_reason, attempt.tests_run)

        if attempt.merged:
            return self._finalize(request, "merged", "GitHub confirmed the validated commit was merged.")

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
            (not is_moonboys_repo(request.repo_target) or bool(request.ci_branch or request.ci_follow_up))
            and (_normalize_repo_slug(request.repo_target) != _normalize_repo_slug(SWARMSY_REPO) or self.swarmsy_auto_merge)
            and attempt.review_verdict == "approved"
            and attempt.merge_ready
        )
        if should_try_merge and self.worker.merge_pr(request, request.swarmsy_pr_url):
            return self._finalize(request, "merged", "Merged automatically after passing policy gates.", attempt.tests_run)

        if attempt.review_verdict == "approved" and attempt.merge_ready and not should_try_merge:
            if is_moonboys_repo(request.repo_target):
                return self._finalize(request, "pr_opened_waiting_review", "Website policy requires a manual merge.")
            return self._finalize(request, "pr_opened_waiting_review", "Codex and CI passed. SWARMSY auto-merge is disabled.")
        return self._finalize(
            request, "pr_opened_waiting_review", attempt.reason or "PR opened and waiting for review/merge policy.", attempt.tests_run
        )
