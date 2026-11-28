from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sqlite3
import tempfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode

from .config import Settings, _normalize_repo_slug
from .doctor_history import HistoryIndex, local_lessons, repo_scope, shared_repo_scope
from .doctor_shared_lessons import shared_search
from .doctor_distillation import retrieve, budget_evidence
from .doctor_telegram import TelegramApproval
from .doctor_ci import MERGE_LABEL, REPAIR_LABEL, audit_workflow, exact_ci, labels, paused
from .doctor_repair import CloudRepairUnavailable, ContainerValidator, DoctorWorkspace, RepairLoop, ci_repair_path, log, path_allowed, scrub, sha
from .git_tools import GITHUB_REPO_SLUG, GitBranchExecutor
from .merge_rules import PROTECTED_CORE_FILES
from .swarmsy_doctor import (
    DoctorEdit, DoctorRepairAttempt, DoctorRequest, DoctorReviewComment, JsonDoctorArchive, is_moonboys_repo, utc_now_iso,
)

CODEX_BOT = "chatgpt-codex-connector[bot]"
CODEX_SUMMARY = re.compile(r"^<!-- codex-review-state:v1 (\{[^\n]+\}) -->$", re.MULTILINE)
PROTECTED_FILES = PROTECTED_CORE_FILES | {
    "pyproject.toml", "package.json", "package-lock.json", "tsconfig.json",
    "src/the_daddy/doctor_repair.py", "src/the_daddy/doctor_worker.py",
    "src/the_daddy/agents/local_repair.py", "src/the_daddy/config.py",
    "src/the_daddy/doctor_telegram.py",
    "src/the_daddy/swarmsy_doctor.py", "src/the_daddy/swarmsy_doctor_queue.py",
    "src/the_daddy/doctor_ci.py", "src/the_daddy/doctor_history.py", "src/the_daddy/doctor_shared_lessons.py", "src/the_daddy/doctor_diagnostics.py", "src/the_daddy/doctor_distillation.py",
}


def is_codex(item: dict) -> bool:
    user = item.get("user") or {}
    return user.get("type") == "Bot" and user.get("login") == CODEX_BOT


def codex_summary(item: dict, head: str) -> dict | None:
    if not is_codex(item):
        return None
    match = CODEX_SUMMARY.search(str(item.get("body") or ""))
    if not match:
        return None
    try:
        review = json.loads(match[1]).get("code_review")
    except (ValueError, AttributeError):
        return None
    return review if isinstance(review, dict) and review.get("commit_sha") == head else None


class GitHubDoctorWorker:
    def __init__(
        self, settings: Settings, archive: JsonDoctorArchive, *,
        validation_image: str, validation_command: str, required_checks: set[str],
        deploy_workflow: str = "", deploy_job: str = "Cloudflare deploy",
        watch_ci: bool = False, dispatch_ci: bool = False,
    ) -> None:
        repo = settings.github_repo.strip()
        if not GITHUB_REPO_SLUG.fullmatch(repo) or repo.split("/")[1] in {".", ".."}:
            raise ValueError("GITHUB_REPO must be a valid GitHub owner/repo.")
        self.settings = settings.model_copy(update={"github_repo": repo})
        self.archive = archive
        self.required_checks = required_checks
        if deploy_workflow and not re.fullmatch(r"[A-Za-z0-9_.-]+\.(?:yml|yaml)", deploy_workflow):
            raise ValueError("Configure Cloudflare tracking with the target workflow file name.")
        self.deploy_workflow = deploy_workflow
        self.deploy_job = deploy_job
        self.ci_workflow = audit_workflow(repo) if watch_ci else ""
        self.dispatch_ci = dispatch_ci
        self.git = GitBranchExecutor(
            github_token=settings.github_token, github_repo=repo, allowed_target_repos=settings.allowed_target_repos,
        )
        validator = ContainerValidator(validation_image, validation_command, settings.run_timeout_seconds)
        self.telegram = TelegramApproval(archive.path, settings.doctor_telegram_required)
        self.repair = RepairLoop(self.settings, validator, self._checkpoint)
        self.history_repos = repo_scope(os.getenv("DADDY_DOCTOR_HISTORY_REPOS", ""), repo)
        self.shared_repos = shared_repo_scope(repo)
        self.history_enabled = os.getenv("DADDY_DOCTOR_HISTORY_ENABLED", "").lower() == "true"
        self.history = HistoryIndex(archive.path.with_suffix(".history.sqlite3"), self.settings)

    def _checkpoint(self, request: DoctorRequest) -> None:
        self.archive.upsert_request(request)
        self.telegram.checkpoint(request)

    def _api(self, method: str, endpoint: str, data: dict | None = None):
        url = f"https://api.github.com/repos/{self.git.github_repo}"
        return self.git._api_request(method, f"{url}/{endpoint}" if endpoint else url, data)

    def _list(self, endpoint: str, *, list_key: str = "") -> list[dict]:
        items = []
        separator = "&" if "?" in endpoint else "?"
        for page in range(1, 11):
            response = self._api("GET", f"{endpoint}{separator}per_page=100&page={page}")
            batch = response.get(list_key) if list_key and isinstance(response, dict) else response
            if not isinstance(batch, list):
                raise RuntimeError("GitHub returned an incomplete review or check response.")
            items.extend(batch)
            if len(batch) < 100:
                return items
        raise RuntimeError("GitHub review or check response exceeded Doctor's pagination limit.")

    @staticmethod
    def _reference(request: DoctorRequest) -> str:
        return hashlib.sha256(request.request_id.encode()).hexdigest()[:20]

    def _branch(self, request: DoctorRequest) -> str:
        return request.ci_branch or f"doctor/repair-{self._reference(request)}"

    def _verify_target(self, request: DoctorRequest) -> None:
        self.git._ensure_target_repo_allowed("Doctor queue processing")
        if _normalize_repo_slug(self.git.github_repo) != _normalize_repo_slug(request.repo_target):
            raise PermissionError("Doctor request does not match the configured GitHub target.")
        if (request.ci_branch or request.ci_follow_up) and not (
            self.ci_workflow and request.source == "daddy" and request.ci_origin_pr > 0
            and 1 <= len(request.allowed_paths) <= 5
            and all(ci_repair_path(path, request.repo_target) and path not in PROTECTED_FILES
                    for path in request.allowed_paths)
        ):
            raise PermissionError("The CI repair is outside the configured functional repair scope.")

    def discover_ci_repairs(self, *, enqueue: bool = False) -> list[dict]:
        """Inspect recent open PRs for the configured target and its known CI workflow."""
        self.git._ensure_target_repo_allowed("Doctor CI scan")
        if not self.ci_workflow:
            raise ValueError("No supported CI workflow is configured for this repository.")
        base_branch, base = self._repo()
        repo = self.git.github_repo
        normalized_repo = _normalize_repo_slug(repo)
        query = urlencode({"state": "open", "base": base_branch, "per_page": 25, "sort": "updated"})
        rows = []
        for pr in self._api("GET", f"pulls?{query}"):
            head = pr.get("head") or {}
            number = int(pr["number"])
            status, url = "unavailable", ""
            if _normalize_repo_slug((head.get("repo") or {}).get("full_name", "")) == normalized_repo:
                status, url, failures = exact_ci(self, sha(head["sha"]), head["ref"])
                if enqueue and status == "failed" and not paused(pr) and REPAIR_LABEL in labels(pr):
                    status = self._adopt_ci_pr(pr, base, base_branch, failures)
            rows.append({"pr": number, "url": f"https://github.com/{repo}/pull/{number}",
                         "ci": status, "ci_url": url, "paused": paused(pr),
                         "repair_selected": REPAIR_LABEL in labels(pr)})
        return rows

    def _adopt_ci_pr(self, pr, base, base_branch, failures) -> str:
        number = int(pr["number"])
        head = sha(pr["head"]["sha"])
        branch = pr["head"]["ref"]
        if branch == base_branch or branch.startswith("doctor/"):
            return "tracked_by_existing_flow"
        # One adoption per repository and PR. Broad or protected diffs stay with the operator.
        request_id = f"ci-pr-{_normalize_repo_slug(self.git.github_repo)}-{number}"
        if self.archive.get_request(request_id):
            return "tracked"
        if pr["base"]["sha"] != base:
            return "waiting_for_current_base"
        comparison = self._api("GET", f"compare/{base}...{head}?per_page=1")
        if comparison.get("merge_base_commit", {}).get("sha") != base:
            return "waiting_for_current_base"
        files = self._api("GET", f"pulls/{number}/files?per_page=6")
        if not 1 <= len(files) <= 5 or any(
            item["status"] not in ("added", "modified") or item["filename"] in PROTECTED_FILES
            or not ci_repair_path(item["filename"], self.git.github_repo) for item in files
        ):
            return "needs_manual_scope"
        req = DoctorRequest(
            request_id=request_id, source="daddy", repo_target=self.git.github_repo,
            problem_summary=f"Repair the reproduced functional test failure on PR #{number}.",
            logs=[scrub(comment.body, self.settings) for comment in failures],
            allowed_paths=[item["filename"] for item in files], ci_branch=branch, ci_origin_pr=number,
            pr_number=number, head_sha=head, base_branch=base_branch, base_sha=base, expected_base_sha=base,
            swarmsy_pr_url=f"https://github.com/{self.git.github_repo}/pull/{number}",
        )
        self._verify_target(req)
        self.archive.enqueue_once(req)
        return "queued"

    def _redact_request(self, request: DoctorRequest) -> None:
        for field in ("problem_summary", "feature_hint", "failing_command", "user_intent"):
            setattr(request, field, scrub(getattr(request, field), self.settings))
        request.logs = [scrub(item, self.settings)[-5000:] for item in request.logs[-20:]]
        request.screenshots = [scrub(item, self.settings) for item in request.screenshots]
        self.archive.upsert_request(request)

    def _repo(self) -> tuple[str, str]:
        metadata = self._api("GET", "")
        if _normalize_repo_slug(metadata["full_name"]) != _normalize_repo_slug(self.git.github_repo):
            raise PermissionError("GitHub returned a different repository.")
        base = metadata["default_branch"]
        branch = self._api("GET", f"branches/{quote(base, safe='')}")
        return base, sha(branch["commit"]["sha"])

    def _head(self, request: DoctorRequest) -> str:
        ref = f"refs/heads/{self._branch(request)}"
        matches = self._api("GET", f"git/matching-refs/heads/{self._branch(request)}")
        return next((sha(item["object"]["sha"]) for item in matches if item["ref"] == ref), "")

    def _history_api(self, repo: str, endpoint: str):
        if repo not in self.history_repos:
            raise PermissionError("Repository is outside the history read scope.")
        return self.git._api_request("GET", f"https://api.github.com/repos/{repo}/{endpoint}")

    def sync_history(self) -> list[dict]:
        return [self.history.sync_page(repo, self._history_api) for repo in self.history_repos]

    def _historical_evidence(self, request: DoctorRequest) -> list[dict]:
        evidence = local_lessons(request, self.archive, self.settings)
        if self.history_enabled:
            try:
                evidence.extend(retrieve(self.history, request, self.history_repos))
            except (RuntimeError, OSError, ValueError, sqlite3.Error):
                log(request, self.settings, "history_unavailable",
                    "GitHub history index unavailable; proceeding with local evidence.",
                    self._checkpoint)
        if os.getenv("DADDY_DOCTOR_INTELLIGENCE_BUCKET", "").strip():
            try:
                evidence.extend(shared_search(self.history, self.settings, request, self.shared_repos))
            except (RuntimeError, OSError, ValueError, sqlite3.Error):
                log(request, self.settings, "shared_history_unavailable",
                    "Shared advisory cache unavailable; proceeding with local evidence.", self._checkpoint)
        return budget_evidence(evidence, self.settings)

    def _memory(self, request: DoctorRequest) -> list[DoctorEdit]:
        summary = " ".join(request.problem_summary.casefold().split())
        for past in sorted(self.archive.all_requests(), key=lambda item: item.updated_at, reverse=True):
            if (
                past.request_id != request.request_id and past.status == "merged" and past.learned_edits
                and re.fullmatch(r"[0-9a-f]{40}", past.head_sha)
                and re.fullmatch(r"[0-9a-f]{40}", past.merge_sha)
                and past.post_merge_ci in {"passed", "unconfigured"}
                and past.deployment_status in {"deployed", "unconfigured"}
                and _normalize_repo_slug(past.repo_target) == _normalize_repo_slug(request.repo_target)
                and " ".join(past.problem_summary.casefold().split()) == summary
                and all(path_allowed(edit.path, request) for edit in past.learned_edits)
            ):
                return past.learned_edits
        return []

    def _stage(
        self, request: DoctorRequest, *, base: str, parent: str, findings: list[str], require_ci_failure: bool = False,
        codex_edits: list[DoctorEdit] | None = None,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="doctor-repair-") as root:
            workspace = DoctorWorkspace(Path(root), self.settings)
            workspace.checkout(parent)
            remembered = self._memory(request) if not findings else []
            try:
                options = {"require_baseline_failure": True} if require_ci_failure else {}
                history = self._historical_evidence(request) if not request.wiki_link else []
                if history:
                    options["history"] = history
                    log(request, self.settings, "history_retrieved", f"Retrieved {len(history)} advisory records.", self._checkpoint)
                if codex_edits:
                    options["codex_edits"] = codex_edits
                edits, digest = self.repair.run(workspace, request, findings, remembered, **options)
            except CloudRepairUnavailable:
                raise
            except RuntimeError as exc:
                raise RuntimeError(scrub(str(exc), self.settings)) from exc
            # Recheck the PR before pushing, including an owner pause while validation ran.
            if request.pr_number:
                self._verify_open_pr(request, parent)
            if request.ci_follow_up and self._repo()[1] != base:
                raise PermissionError("The default branch advanced while validating the CI follow-up.")
            request.pending_head_sha = workspace.commit(self._reference(request))
            request.pending_base_sha = base
            request.pending_diff_digest = digest
            request.pending_edits = edits
            request.delivery_retries = 0
            request.tests_run = list(dict.fromkeys([*request.tests_run, shlex.join(self.repair.validator.command)]))
            log(request, self.settings, "delivery_prepared", request.pending_head_sha, self._checkpoint)
            workspace.push(self._branch(request), request.pending_head_sha, request.head_sha)

    def _publish(self, request: DoctorRequest, base_branch: str) -> DoctorRepairAttempt:
        website = is_moonboys_repo(request.repo_target)
        if (website or request.ci_follow_up) and request.pending_base_sha != self._repo()[1]:
            raise PermissionError("The website advanced during validation. Request a fresh review of the case.")
        remote = self._head(request)
        if request.pr_number:
            self._verify_open_pr(request, remote)
        if remote != request.pending_head_sha:
            if remote != request.head_sha:
                raise PermissionError("Doctor repair branch changed outside the validated delivery.")
            if request.delivery_retries >= 3:
                raise PermissionError("Doctor exhausted push retries. Check the GitHub token and branch rules.")
            request.delivery_retries += 1
            self.archive.upsert_request(request)
            with tempfile.TemporaryDirectory(prefix="doctor-delivery-") as root:
                workspace = DoctorWorkspace(Path(root), self.settings)
                workspace.checkout(request.head_sha or request.pending_base_sha)
                workspace.apply(request, request.pending_edits)
                if hashlib.sha256(workspace.diff().encode()).hexdigest() != request.pending_diff_digest:
                    raise PermissionError("Persisted repair does not reproduce the tested and reviewed diff.")
                request.pending_head_sha = workspace.commit(self._reference(request))
                self.archive.upsert_request(request)
                workspace.push(self._branch(request), request.pending_head_sha, request.head_sha)
        if not request.pr_number:
            ref = self._reference(request)
            body = (
                "Doctor validated this repair locally and obtained an API review. "
                "The pull request will receive a separate Codex review."
            )
            if website:
                files = ", ".join(f"`{path}`" for path in sorted({edit.path for edit in request.pending_edits}))
                body = (
                    f"Approved Telegram case #{request.request_id.split('-')[1]}. "
                    f"Changed website frontend files: {files}.\n\n"
                    f"Doctor ran the configured isolated website validation against `{request.pending_base_sha}` "
                    "and obtained a separate API review of the candidate. Codex review is requested on the validated head. "
                    "Live browser verification and release checks remain pending. "
                    "The repair changes no Worker configuration or D1 schema.\n\n"
                    "**Merge/deploy/migrate remains pending GK approval.**"
                )
            if request.pending_codex_only:
                body = body.replace("and obtained an API review. ", ". OpenAI approval unavailable; ")\
                    .replace("and obtained a separate API review of the candidate. ", "OpenAI approval unavailable. ")
                body += "\n\nLocally validated candidate only. Independent exact-head Codex review and required CI remain mandatory."
            pr = self.git.create_pull_request(
                self._branch(request), f"fix: Doctor repair {ref}", body, base_branch=base_branch,
            )
            if not pr or int(pr["number"]) <= 0:
                raise RuntimeError("GitHub did not return a Doctor pull request.")
            self._verify_pr(request, pr, request.pending_head_sha, base_branch)
            request.pr_number = int(pr["number"])
            request.swarmsy_pr_url = f"https://github.com/{self.git.github_repo}/pull/{request.pr_number}"
        else:
            pr = self._api("GET", f"pulls/{request.pr_number}")
            self._verify_pr(request, pr, request.pending_head_sha, base_branch)
            if pr["state"] != "open" or pr["draft"]:
                raise PermissionError("The Doctor pull request was closed or converted to draft during delivery.")
        request.head_sha = request.pending_head_sha
        request.codex_only_head = request.head_sha if request.pending_codex_only else ""
        request.pending_codex_only = False
        request.codex_patch_requested_head = ""
        request.base_branch = base_branch
        request.base_sha = request.pending_base_sha
        request.learned_edits = [*request.learned_edits, *request.pending_edits]
        request.pending_head_sha = request.pending_base_sha = request.pending_diff_digest = ""
        request.pending_edits = []
        request.review_request_id = 0
        log(request, self.settings, "pr_head_published", request.head_sha, self._checkpoint)
        self._request_review(request)
        return self._attempt(request, reason="Waiting for Codex to review the validated commit.")

    def _verify_open_pr(self, request: DoctorRequest, expected_head: str) -> dict:
        pr = self._api("GET", f"pulls/{request.pr_number}")
        self._verify_pr(request, pr, expected_head, request.base_branch)
        if pr.get("state") != "open":
            raise PermissionError("PR closed during validation.")
        if paused(pr) or (request.ci_branch and REPAIR_LABEL not in labels(pr)):
            raise RuntimeError("PR is paused, draft, or no longer selected for CI repair.")
        return pr

    def _verify_pr(self, request: DoctorRequest, pr: dict, expected_head: str, base_branch: str) -> None:
        head = pr["head"]
        base = pr["base"]
        repo = _normalize_repo_slug(self.git.github_repo)
        if (
            _normalize_repo_slug((head.get("repo") or {}).get("full_name", "")) != repo
            or _normalize_repo_slug((base.get("repo") or {}).get("full_name", "")) != repo
            or head["ref"] != self._branch(request) or base["ref"] != base_branch
            or head["sha"] != sha(expected_head)
        ):
            raise PermissionError("Pull request repository, branches, or head differ from the validated Doctor delivery.")

    def _request_review(self, request: DoctorRequest) -> None:
        if request.review_request_id:
            return
        head = sha(request.head_sha)
        endpoint = f"issues/{request.pr_number}/comments"
        body = (
            f"@codex review this exact commit {head}. For each finding, give the concrete fix "
            "with file, line and suggested replacement or patch. If the commit is ready, "
            f"include a line reading `DOCTOR_REVIEW_APPROVED {head}` in the completed review.\n\n"
            f"<!-- doctor-review:{head} -->"
        )
        if self.settings.doctor_codex_fallback:
            body += self._patch_contract(head)
        actor = self.git._api_request("GET", "https://api.github.com/user")["login"]
        existing = next((item for item in self._list(endpoint)
                         if item.get("body") == body and (item.get("user") or {}).get("login") == actor), None)
        comment = existing or self._api("POST", endpoint, {"body": body})
        request.review_request_id = int(comment["id"])
        log(request, self.settings, "codex_review_requested", head, self._checkpoint)

    @staticmethod
    def _patch_contract(head: str) -> str:
        return ("\n\nFor each actionable finding include a concrete exact-text edit as JSON "
                "in a fenced json block preceded by the line DOCTOR_PATCH " + head
                + ". The JSON must be an array of objects with path, old, new keys only. "
                "Use unique exact old spans from this commit. Do not push commits, run commands, "
                "change credentials, alter approval gates or edit outside the requested scope.")

    def _codex_edits(self, request: DoctorRequest, comments: list[DoctorReviewComment]) -> list[DoctorEdit]:
        """Only consume exact-head structured edits from already authenticated review findings."""
        head = sha(request.head_sha)
        edits: list[DoctorEdit] = []
        seen = set()
        for comment in comments:
            if comment.author != CODEX_BOT:
                return []
            pattern = re.compile(r"(?m)^DOCTOR_PATCH " + head + r"\s*\n```json\s*\n([\s\S]*?)\n```\s*$")
            matches = pattern.findall(comment.body)
            if len(matches) != 1 or len(matches[0].encode()) > 24000:
                return []
            try:
                raw = json.loads(matches[0])
                if not isinstance(raw, list) or not 1 <= len(raw) <= 20:
                    return []
                for item in raw:
                    edit = DoctorEdit.model_validate(item)
                    if edit.path in PROTECTED_FILES or not path_allowed(edit.path, request):
                        return []
                    identity = (edit.path, edit.old, edit.new)
                    if identity not in seen:
                        seen.add(identity)
                        edits.append(edit)
            except (ValueError, TypeError):
                return []
        return edits if len(edits) <= 20 and len({edit.path for edit in edits}) <= 5 else []

    def _request_codex_patch(self, request: DoctorRequest) -> None:
        head = sha(request.head_sha)
        if request.codex_patch_requested_head == head:
            return
        endpoint = f"issues/{request.pr_number}/comments"
        body = (f"@codex review exact commit {head}. Doctor needs a concrete repair proposal "
                "because its cloud repair provider is unavailable. Review the existing findings and "
                "failed tests. Return scoped edits, not direct commits.\n"
                f"<!-- doctor-patch-request:{head} -->" + self._patch_contract(head))
        actor = self.git._api_request("GET", "https://api.github.com/user")["login"]
        existing = next((item for item in self._list(endpoint)
                         if item.get("body") == body and (item.get("user") or {}).get("login") == actor), None)
        comment = existing or self._api("POST", endpoint, {"body": body})
        request.codex_patch_requested_head = head
        # A new review request must not use a reaction on the old request.
        request.review_request_id = int(comment["id"])
        log(request, self.settings, "codex_patch_requested", head, self._checkpoint)

    def _pending_codex_patch(self, request: DoctorRequest) -> list[DoctorReviewComment]:
        """A patch request is not an approval request, even on the same head."""
        number = request.pr_number
        comments = self._list(f"issues/{number}/comments")
        marker = f"<!-- doctor-patch-request:{request.head_sha} -->"
        anchor = next((item for item in comments
                       if item.get("id") == request.review_request_id
                       and marker in str(item.get("body") or "")), None)
        if not anchor or not anchor.get("created_at"):
            return []
        since = anchor["created_at"]
        candidates = []
        reviews = self._list(f"pulls/{number}/reviews")
        for review in reviews:
            if (not is_codex(review) or review.get("commit_id") != request.head_sha
                    or review.get("state") not in {"APPROVED", "COMMENTED", "CHANGES_REQUESTED"}
                    or (review.get("submitted_at") or "") <= since):
                continue
            for item in self._list(f"pulls/{number}/reviews/{int(review['id'])}/comments"):
                if is_codex(item) and item.get("commit_id") == request.head_sha:
                    candidates.append(DoctorReviewComment(author=CODEX_BOT, body=str(item.get("body") or "")))
            candidates.append(DoctorReviewComment(author=CODEX_BOT, body=str(review.get("body") or "")))
        for item in comments:
            if is_codex(item) and (item.get("created_at") or "") > since:
                candidates.append(DoctorReviewComment(author=CODEX_BOT, body=str(item.get("body") or "")))
        # A standalone patch can include several edits. Ignore explanatory
        # comments without a patch; reject ambiguous competing patch proposals.
        valid = [item for item in candidates if self._codex_edits(request, [item])]
        if len(valid) != 1:
            return []
        return valid

    def _attempt(self, request: DoctorRequest, **kwargs) -> DoctorRepairAttempt:
        return DoctorRepairAttempt(
            validation_passed=bool(request.head_sha), pr_url=request.swarmsy_pr_url, tests_run=request.tests_run, **kwargs,
        )

    def run_initial_repair(self, request: DoctorRequest) -> DoctorRepairAttempt:
        self._verify_target(request)
        self._redact_request(request)
        base_branch, base = self._repo()
        if (is_moonboys_repo(request.repo_target) or request.ci_follow_up) and base != request.expected_base_sha:
            raise PermissionError("The website advanced since the reviewed commit. Request a fresh review of the case.")
        if self._head(request):
            raise PermissionError("A branch already exists without a validated Doctor delivery record.")
        if request.ci_follow_up:
            self._stage(request, base=base, parent=base, findings=request.logs, require_ci_failure=True)
        else:
            self._stage(request, base=base, parent=base, findings=[])
        return self._publish(request, base_branch)

    def apply_review_comment_fixes(
        self, request: DoctorRequest, actionable_comments: list[DoctorReviewComment], cycle: int,
    ) -> DoctorRepairAttempt:
        self._verify_target(request)
        base_branch, base = self._repo()
        if base != request.base_sha:
            raise PermissionError("Base advanced; the existing Doctor PR needs a fresh repair against the current base.")
        pr = self._api("GET", f"pulls/{request.pr_number}")
        self._verify_pr(request, pr, request.head_sha, base_branch)
        if pr["state"] != "open" or paused(pr) or (request.ci_branch and REPAIR_LABEL not in labels(pr)):
            raise PermissionError("The Doctor pull request must be open and ready for review.")
        if self.telegram.enabled:
            decision = self.telegram.decision(request)
            if decision == "unavailable":
                request.review_cycles = max(0, request.review_cycles - 1)
                self.archive.upsert_request(request)
                return self._attempt(request, reason="Waiting for Telegram before editing.")
            if decision == "rejected":
                raise PermissionError("Owner rejected the repair in Telegram. PR retained.")
            if any(comment.author == "Telegram owner" for comment in actionable_comments) and decision != "fix_requested":
                request.review_cycles = max(0, request.review_cycles - 1)
                self.archive.upsert_request(request)
                return self._attempt(request, reason="Further-fix decision is no longer current.")
            if decision in ("ready", "approved"):
                if self.telegram.decision(request, "invalidate") != "invalidated":
                    request.review_cycles = max(0, request.review_cycles - 1)
                    self.archive.upsert_request(request)
                    return self._attempt(request, reason="Waiting to invalidate previous Telegram approval before editing.")
        findings = [comment.body for comment in actionable_comments]
        log(request, self.settings, f"codex_fix_cycle_{cycle}", "\n".join(findings), self._checkpoint)
        codex_edits = self._codex_edits(request, actionable_comments) if self.settings.doctor_codex_fallback else []
        require_failure = bool(self.ci_workflow and (
            any(comment.author == "GitHub CI" for comment in actionable_comments)
            or (request.ci_branch and not request.learned_edits)))
        options = {"require_ci_failure": True} if require_failure else {}
        if codex_edits:
            options["codex_edits"] = codex_edits
        try:
            self._stage(request, base=base, parent=request.head_sha, findings=findings, **options)
        except CloudRepairUnavailable:
            if not self.settings.doctor_codex_fallback or request.wiki_link:
                raise
            if codex_edits:
                # A concrete proposal that failed validation consumes its cycle.
                # Do not reapply it indefinitely or accept approval of the old head.
                raise PermissionError("Codex patch did not produce a passing candidate; owner review required.") from None
            self._request_codex_patch(request)
            if not codex_edits:
                # Waiting for a concrete response is not a new repair attempt.
                request.review_cycles = max(0, request.review_cycles - 1)
                self.archive.upsert_request(request)
            return self._attempt(request, reason="Waiting for concrete exact-head Codex edits; OpenAI unavailable.")
        return self._publish(request, base_branch)

    def _codex_review(self, request: DoctorRequest) -> tuple[str, list[DoctorReviewComment]]:
        number = request.pr_number
        head = request.head_sha
        reviews = self._list(f"pulls/{number}/reviews")
        changes_requested = {}
        for review in reviews:
            login = (review.get("user") or {}).get("login")
            if login and not is_codex(review) and review.get("state") in {"CHANGES_REQUESTED", "APPROVED", "DISMISSED"}:
                changes_requested[login] = review["state"] == "CHANGES_REQUESTED"
        if any(changes_requested.values()):
            raise PermissionError("A GitHub reviewer has requested changes on this PR. Review their decision on GitHub.")
        completed = [
            review for review in reviews if is_codex(review) and review.get("commit_id") == head
            and review.get("state") in {"APPROVED", "COMMENTED", "CHANGES_REQUESTED"}
        ]
        marker = f"DOCTOR_REVIEW_APPROVED {head}"
        decisive = None
        findings: list[DoctorReviewComment] = []
        for review in sorted(completed, key=lambda item: (item.get("submitted_at") or "", int(item["id"])), reverse=True):
            inline = [
                DoctorReviewComment(comment_id=str(item["id"]), author=CODEX_BOT,
                                    body=f"Codex finding in {item.get('path', '')}: {item.get('body', '')}")
                for item in self._list(f"pulls/{number}/reviews/{int(review['id'])}/comments") if is_codex(item)
            ]
            body = str(review.get("body") or "").strip()
            if review["state"] == "CHANGES_REQUESTED":
                inline.append(DoctorReviewComment(author=CODEX_BOT, body=f"Codex requested changes: {body}"))
            if inline or review["state"] == "APPROVED" or marker in body.splitlines():
                decisive = review
                findings = inline
                break
        # The live integration publishes a commit-bound summary even when it
        # reports no findings through a PR-wide reaction instead of a review.
        summaries = self._list(f"issues/{number}/comments")
        for item in reversed(summaries):
            summary = codex_summary(item, head)
            if summary is None:
                continue
            reviewed_at = (decisive or {}).get("submitted_at") or ""
            summarized_at = item.get("updated_at") or ""
            clean = (summary.get("status") == "completed" and summary.get("has_any_findings") is False
                     and summary.get("has_unresolved_findings") is False)
            if clean and (not findings or summarized_at > reviewed_at):
                return "approved", []
            if decisive and (reviewed_at > summarized_at or findings and summary.get("status") == "completed"):
                break
            return "pending", []
        if decisive:
            return ("changes_requested", findings) if findings else ("approved", [])
        # The GitHub integration can mark a clean review with a reaction. Only a
        # reaction on Doctor's commit-specific request can identify the commit.
        reactions = self._list(f"issues/comments/{request.review_request_id}/reactions")
        if any(is_codex(item) and item.get("content") == "+1" for item in reactions):
            return "approved", []
        return "pending", []

    def _ci_review(self, head: str) -> tuple[bool, list[DoctorReviewComment]]:
        if not self.required_checks:
            return False, []
        runs = self._list(f"commits/{sha(head)}/check-runs?filter=latest", list_key="check_runs")
        statuses = self._list(f"commits/{head}/statuses")
        current_statuses = {}
        for status in statuses:
            current_statuses.setdefault(status["context"], status)
        checks = {}
        for run in runs:
            if run.get("head_sha") == head:
                checks.setdefault(run["name"], []).append(run)
        failures = []
        for name in sorted(self.required_checks):
            for run in checks.get(name, []):
                if run.get("conclusion") in {"failure", "timed_out"}:
                    output = run.get("output") or {}
                    evidence = "\n".join(str(output.get(field) or "") for field in ("title", "summary", "text"))
                    failures.append(DoctorReviewComment(author="GitHub CI", body=f"CI check {name} failed. {evidence}"))
            status = current_statuses.get(name, {})
            if status.get("state") == "failure":
                failures.append(DoctorReviewComment(author="GitHub CI", body=f"CI status {name} failed. {status.get('description', '')}"))
        passed = all(
            (name in checks or name in current_statuses)
            and all(run.get("conclusion") == "success" for run in checks.get(name, []))
            and current_statuses.get(name, {}).get("state", "success") == "success"
            for name in self.required_checks
        )
        return passed, failures

    def poll_review(self, request: DoctorRequest) -> DoctorRepairAttempt:
        self._verify_target(request)
        base_branch, base = self._repo()
        if request.pending_head_sha:
            return self._publish(request, base_branch)
        pr = self._api("GET", f"pulls/{request.pr_number}")
        try:
            self._verify_pr(request, pr, request.head_sha, base_branch)
        except PermissionError:
            if self.telegram.enabled:
                self.telegram.decision(request, "invalidate")
            raise
        if pr.get("merged") is True:
            self._record_merge(request, pr["merge_commit_sha"], base_branch)
            return self._attempt(request, merged=True)
        if pr["state"] != "open":
            if self.telegram.enabled:
                self.telegram.decision(request, "invalidate")
            raise PermissionError("The Doctor pull request is closed.")
        if paused(pr) or (request.ci_branch and REPAIR_LABEL not in labels(pr)):
            if self.telegram.enabled:
                self.telegram.decision(request, "invalidate")
            return self._attempt(request, reason="PR is paused, draft, or no longer selected for CI repair.")
        if request.base_sha != base or pr["base"]["sha"] != base:
            if self.telegram.enabled:
                self.telegram.decision(request, "invalidate")
            raise PermissionError("Base advanced after Doctor validated this commit. Revalidate before merging.")
        if request.codex_patch_requested_head == request.head_sha:
            if not self.settings.doctor_codex_fallback:
                return self._attempt(request, reason="Codex fallback is disabled with an outstanding patch request; merge blocked.")
            if self.telegram.enabled:
                decision = self.telegram.decision(request)
                if decision == "rejected":
                    raise PermissionError("Owner rejected the repair in Telegram. PR retained.")
                self.telegram.decision(request, "invalidate")
            comments = self._pending_codex_patch(request)
            if comments:
                return self._attempt(request, review_comments=comments, review_verdict="changes_requested",
                                     reason="Codex supplied a fresh exact-head repair proposal.")
            return self._attempt(request, reason="Waiting for concrete exact-head Codex edits; merge blocked.")
        if request.ci_branch and not request.learned_edits:
            status, _, findings = exact_ci(self, request.head_sha, request.ci_branch)
            return self._attempt(request, review_comments=findings,
                                 reason=f"Selected PR is waiting on its exact-head functional CI failure ({status}).")
        self._request_review(request)
        verdict, comments = self._codex_review(request)
        if verdict != "approved":
            if self.telegram.enabled:
                self.telegram.decision(request, "invalidate")
            return self._attempt(request, review_verdict=verdict, review_comments=comments,
                                 reason="Waiting for a completed Codex review of this exact commit.")
        if self.ci_workflow:
            status, _, findings = self._request_ci(request, request.head_sha, self._branch(request))
            if findings and (request.wiki_link or any(
                    not ci_repair_path(path, request.repo_target) or path in PROTECTED_FILES
                    for path in request.allowed_paths)):
                return self._attempt(request, reason="The failed CI check requires manual investigation.")
            if findings:
                return self._attempt(request, review_verdict="changes_requested", review_comments=findings,
                                     reason="The exact-head CI suite found a functional failure.")
            if status != "passed":
                if self.telegram.enabled:
                    self.telegram.decision(request, "invalidate")
                return self._attempt(request, reason=f"Waiting for exact-head CI ({status}).")
        website_support = is_moonboys_repo(request.repo_target) and not (request.ci_branch or request.ci_follow_up)
        if website_support and not self.telegram.enabled:
            return self._attempt(request, review_verdict="approved", reason="Codex approved. Website merge and release require GK approval.")
        passed, failures = self._ci_review(request.head_sha)
        if failures:
            if self.telegram.enabled:
                self.telegram.decision(request, "invalidate")
            return self._attempt(request, review_verdict="changes_requested", review_comments=failures,
                                 reason="Required GitHub CI checks requested follow-up.")
        if not request.learned_edits or any(edit.path in PROTECTED_FILES for edit in request.learned_edits):
            return self._attempt(request, review_verdict="approved", reason="Codex approved. Protected files require a manual merge.")
        label_ok = not (request.ci_branch or request.ci_follow_up) or MERGE_LABEL in labels(pr)
        ready = pr.get("mergeable") is True and pr.get("mergeable_state") == "clean" and passed and label_ok
        if self.telegram.enabled:
            if not ready:
                self.telegram.decision(request, "invalidate")
            else:
                decision = self.telegram.decision(request, "ready")
                if decision == "rejected":
                    raise PermissionError("Owner rejected the repair in Telegram. PR retained.")
                if decision == "fix_requested":
                    return self._attempt(request, review_verdict="changes_requested", review_comments=[
                        DoctorReviewComment(author="Telegram owner", body=(
                            "Owner requested another repair pass on this exact candidate. Reassess the original "
                            "problem and current diff for a concrete remaining defect within the existing approved "
                            "scope. Do not invent a defect or make cosmetic changes just to create a new commit. "
                            "If no substantive correction is justified, return blocked and leave the PR unmerged."
                        ))
                    ], reason="Owner requested further repair; merge blocked until a new validated commit and approval.")
                if decision != "approved":
                    return self._attempt(request, review_verdict="approved",
                                         reason="Waiting for exact-commit Telegram approval.")
        return self._attempt(request, review_verdict="approved", merge_ready=ready,
                             reason="Codex approved. Waiting for required checks or repository merge policy.")

    def merge_pr(self, request: DoctorRequest, pr_url: str) -> bool:
        ready = self.poll_review(request)
        if ready.merged:
            return True
        if is_moonboys_repo(request.repo_target) and not (request.ci_branch or request.ci_follow_up):
            return False
        if ready.review_verdict != "approved" or not ready.merge_ready:
            return False
        if self.telegram.enabled and self.telegram.decision(request) != "approved":
            return False
        outcome = self.git.merge_pull_request(request.pr_number, head_sha=request.head_sha)
        if not outcome or outcome.get("merged") is not True:
            return False
        self._record_merge(request, outcome["sha"], request.base_branch)
        self.telegram.record_merge(request)
        return True

    def merge_approved_website_pr(
        self, request: DoctorRequest, approved_head: str, pr: dict,
    ) -> tuple[str, str]:
        """Merge a validated website commit after the support bridge verifies owner approval."""
        self._verify_target(request)
        if (not is_moonboys_repo(request.repo_target) or request.source != "daddy"
                or not re.fullmatch(r"support-[1-9][0-9]*-[1-9][0-9]*", request.request_id)
                or request.head_sha != sha(approved_head)
                or request.pending_head_sha or not request.review_request_id):
            raise PermissionError("Website merge approval must identify the reviewed Doctor commit.")
        if request.codex_patch_requested_head == request.head_sha:
            return "", ""
        if self.telegram.enabled:
            # The Brain bridge must use the single shared approval authority.
            # An old bridge that passes a legacy approval cannot bypass this check.
            pr = self._api("GET", f"pulls/{request.pr_number}")
            if self._repo() != ("main", request.base_sha):
                return "merge_blocked", "The website base changed after approval."
            if self.telegram.decision(request) != "approved":
                return "", ""
            if self._codex_review(request)[0] != "approved":
                return "", ""
        self._verify_pr(request, pr, approved_head, "main")
        if pr.get("state") != "open" or paused(pr) or pr["base"]["sha"] != request.base_sha:
            return "merge_blocked", "The website pull request changed after validation."
        passed, failures = self._ci_review(approved_head)
        if failures:
            return "merge_blocked", "A required GitHub check failed. Review the checks on the pull request."
        if not passed or pr.get("mergeable") is None:
            return "", ""
        if self.ci_workflow and exact_ci(self, approved_head, self._branch(request))[0] != "passed":
            return "", ""
        if pr.get("mergeable") is not True or pr.get("mergeable_state") != "clean":
            return "merge_blocked", "GitHub reports a merge conflict, missing review, or branch rule. Check the pull request."
        if self.telegram.enabled and self.telegram.decision(request) != "approved":
            return "", ""
        try:
            result = self._api("PUT", f"pulls/{request.pr_number}/merge",
                               {"sha": approved_head, "merge_method": "squash"})
        except RuntimeError as exc:
            if isinstance(exc.__cause__, HTTPError) and exc.__cause__.code in {403, 405, 409, 422}:
                return "merge_blocked", "GitHub blocked the merge. Check the token permissions and branch rules on the pull request."
            raise
        if not isinstance(result, dict) or result.get("merged") is not True:
            return "merge_blocked", "GitHub did not confirm the merge. Check the pull request."
        if result.get("sha"):
            request.merge_sha = sha(result["sha"])
            self.telegram.record_merge(request)
        return "merged", "GitHub merged the commit you approved in Telegram."

    def _record_merge(self, request: DoctorRequest, commit: str, branch: str) -> None:
        request.merge_sha = sha(commit)
        request.base_branch = branch
        if self.ci_workflow:
            request.post_merge_ci = "pending"
            request.post_merge_ci_reason = "Waiting for CI on the exact merge commit."
        if self.deploy_workflow:
            request.deployment_workflow = self.deploy_workflow
            request.deployment_job = self.deploy_job
            request.deployment_status = "pending"
            request.deployment_reason = "Waiting for the target's Cloudflare deployment workflow."

    def _request_ci(self, request: DoctorRequest, commit: str, branch: str, *, merged: bool = False):
        result = exact_ci(self, commit, branch, merged=merged)
        if result[0] != "missing" or not self.dispatch_ci or request.ci_dispatched_ref == commit:
            return result
        current = self._api("GET", f"branches/{quote(branch, safe='')}")["commit"]["sha"]
        if current != commit:
            return "ref_advanced", "", []
        # Record dispatch intent before the API write so retries never spam CI after a timeout.
        request.ci_dispatched_ref = commit
        self.archive.upsert_request(request)
        try:
            self._api("POST", f"actions/workflows/{self.ci_workflow}/dispatches", {"ref": branch})
        except RuntimeError as exc:
            if isinstance(exc.__cause__, HTTPError):
                return "dispatch_failed", "", []
            raise
        return "pending", "", []

    def poll_merged_ci(self, request: DoctorRequest) -> None:
        if not self.ci_workflow:
            return
        self._verify_target(request)
        commit = sha(request.merge_sha)
        status, url, findings = self._request_ci(request, commit, request.base_branch, merged=True)
        if status == "missing" and request.ci_dispatched_ref != commit:
            if self._repo() != (request.base_branch, commit):
                status = "ref_advanced"
        request.post_merge_ci_url = url
        if status == "passed":
            request.post_merge_ci = "passed"
            request.post_merge_ci_reason = "CI passed on the exact merge commit."
        elif status in ("interrupted", "blocked", "ref_advanced", "dispatch_failed"):
            request.post_merge_ci = "needs_review"
            request.post_merge_ci_reason = f"Post-merge CI needs operator review ({status})."
        elif status == "failed":
            base_branch, base = self._repo()
            if (base == commit and base_branch == request.base_branch and not (request.wiki_link or request.ci_follow_up)
                    and 1 <= len(request.allowed_paths) <= 5 and all(
                        ci_repair_path(path, request.repo_target) and path not in PROTECTED_FILES
                        for path in request.allowed_paths)):
                follow_up = self.archive.enqueue_once(DoctorRequest(
                    request_id=f"ci-follow-up-{_normalize_repo_slug(request.repo_target)}-{commit}",
                    repo_target=request.repo_target,
                    source="daddy", ci_follow_up=True, ci_origin_pr=request.pr_number,
                    expected_base_sha=commit, allowed_paths=request.allowed_paths,
                    problem_summary=f"Investigate the functional CI failure after merging PR #{request.pr_number}.",
                    logs=[scrub(comment.body, self.settings) for comment in findings],
                ))
                request.post_merge_ci = "follow_up_queued"
                request.post_merge_ci_reason = f"Follow-up recorded as {follow_up.request_id}."
            else:
                request.post_merge_ci = "needs_review"
                request.post_merge_ci_reason = "CI failed. The branch advanced, the scope is protected, or a follow-up was already tried."
        else:
            request.post_merge_ci_reason = f"Waiting for CI on the exact merge commit ({status})."
        request.updated_at = utc_now_iso()
        self.archive.upsert_request(request)

    def poll_deployment(self, request: DoctorRequest) -> None:
        try:
            self._verify_target(request)
            commit = sha(request.merge_sha)
            query = urlencode({"head_sha": commit, "branch": request.base_branch, "event": "push"})
            workflow = quote(request.deployment_workflow, safe="")
            runs = self._list(f"actions/workflows/{workflow}/runs?{query}", list_key="workflow_runs")
            matching = [run for run in runs if run.get("head_sha") == commit and run.get("event") == "push"
                        and run.get("head_branch") == request.base_branch]
            if matching:
                run = max(matching, key=lambda item: int(item["id"]))
                run_id = int(run["id"])
                request.deployment_url = f"https://github.com/{self.git.github_repo}/actions/runs/{run_id}"
                if run.get("status") == "completed":
                    jobs = self._list(f"actions/runs/{run_id}/jobs?filter=latest", list_key="jobs")
                    matches = [job for job in jobs if job.get("name") == request.deployment_job]
                    if not matches:
                        matches = [job for job in jobs if str(job.get("name", "")).rsplit(" / ", 1)[-1] == request.deployment_job]
                    deployed = (run.get("conclusion") == "success" and len(matches) == 1
                                and matches[0].get("conclusion") == "success")
                    request.deployment_status = "deployed" if deployed else "failed"
                    request.deployment_reason = (
                        "Cloudflare deployment job passed for the merged commit." if deployed
                        else f"Cloudflare job {request.deployment_job!r} did not pass. Workflow conclusion was {run.get('conclusion')}."
                    )
                else:
                    request.deployment_reason = "Cloudflare deployment workflow is running or awaiting approval."
        except RuntimeError as exc:
            request.deployment_reason = scrub(str(exc), self.settings)[-1500:]
        except (PermissionError, ValueError) as exc:
            request.deployment_status = "failed"
            request.deployment_reason = scrub(str(exc), self.settings)[-1500:]
        request.updated_at = utc_now_iso()
        self.archive.upsert_request(request)
