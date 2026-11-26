from __future__ import annotations

import hashlib
import json
import re
import shlex
import tempfile
from pathlib import Path
from urllib.parse import quote, urlencode

from .config import Settings, _normalize_repo_slug
from .doctor_repair import ContainerValidator, DoctorWorkspace, RepairLoop, log, scrub, sha
from .git_tools import GITHUB_REPO_SLUG, GitBranchExecutor
from .merge_rules import PROTECTED_CORE_FILES
from .swarmsy_doctor import (
    DoctorEdit, DoctorRepairAttempt, DoctorRequest, DoctorReviewComment, JsonDoctorArchive, utc_now_iso,
)

CODEX_BOT = "chatgpt-codex-connector[bot]"
CODEX_SUMMARY = re.compile(r"^<!-- codex-review-state:v1 (\{[^\n]+\}) -->$", re.MULTILINE)
PROTECTED_FILES = PROTECTED_CORE_FILES | {
    "pyproject.toml", "package.json", "package-lock.json", "tsconfig.json",
    "src/the_daddy/doctor_repair.py", "src/the_daddy/doctor_worker.py",
    "src/the_daddy/swarmsy_doctor.py", "src/the_daddy/swarmsy_doctor_queue.py",
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
        self.git = GitBranchExecutor(
            github_token=settings.github_token, github_repo=repo, allowed_target_repos=settings.allowed_target_repos,
        )
        validator = ContainerValidator(validation_image, validation_command, settings.run_timeout_seconds)
        self.repair = RepairLoop(self.settings, validator, self.archive.upsert_request)

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
        return f"doctor/repair-{self._reference(request)}"

    def _verify_target(self, request: DoctorRequest) -> None:
        self.git._ensure_target_repo_allowed("Doctor queue processing")
        if _normalize_repo_slug(self.git.github_repo) != _normalize_repo_slug(request.repo_target):
            raise PermissionError("Doctor request does not match the configured GitHub target.")

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

    def _memory(self, request: DoctorRequest) -> list[DoctorEdit]:
        summary = " ".join(request.problem_summary.casefold().split())
        for past in self.archive.recent_requests(limit=100):
            if (
                past.request_id != request.request_id and past.status == "merged" and past.learned_edits
                and _normalize_repo_slug(past.repo_target) == _normalize_repo_slug(request.repo_target)
                and " ".join(past.problem_summary.casefold().split()) == summary
            ):
                return past.learned_edits
        return []

    def _stage(
        self, request: DoctorRequest, *, base: str, parent: str, findings: list[str],
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="doctor-repair-") as root:
            workspace = DoctorWorkspace(Path(root), self.settings)
            workspace.checkout(parent)
            remembered = self._memory(request) if not findings else []
            try:
                edits, digest = self.repair.run(workspace, request, findings, remembered)
            except RuntimeError as exc:
                raise RuntimeError(scrub(str(exc), self.settings)) from exc
            request.pending_head_sha = workspace.commit(self._reference(request))
            request.pending_base_sha = base
            request.pending_diff_digest = digest
            request.pending_edits = edits
            request.delivery_retries = 0
            request.tests_run = list(dict.fromkeys([*request.tests_run, shlex.join(self.repair.validator.command)]))
            log(request, self.settings, "delivery_prepared", request.pending_head_sha, self.archive.upsert_request)
            workspace.push(self._branch(request), request.pending_head_sha, request.head_sha)

    def _publish(self, request: DoctorRequest, base_branch: str) -> DoctorRepairAttempt:
        remote = self._head(request)
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
            pr = self.git.create_pull_request(
                self._branch(request), f"fix: Doctor repair {ref}",
                "Doctor validated this repair locally and obtained an API review. "
                "The pull request will receive a separate Codex review.",
                base_branch=base_branch,
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
        request.base_branch = base_branch
        request.base_sha = request.pending_base_sha
        request.learned_edits = [*request.learned_edits, *request.pending_edits]
        request.pending_head_sha = request.pending_base_sha = request.pending_diff_digest = ""
        request.pending_edits = []
        request.review_request_id = 0
        log(request, self.settings, "pr_head_published", request.head_sha, self.archive.upsert_request)
        self._request_review(request)
        return self._attempt(request, reason="Waiting for Codex to review the validated commit.")

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
        actor = self.git._api_request("GET", "https://api.github.com/user")["login"]
        existing = next((item for item in self._list(endpoint)
                         if item.get("body") == body and (item.get("user") or {}).get("login") == actor), None)
        comment = existing or self._api("POST", endpoint, {"body": body})
        request.review_request_id = int(comment["id"])
        log(request, self.settings, "codex_review_requested", head, self.archive.upsert_request)

    def _attempt(self, request: DoctorRequest, **kwargs) -> DoctorRepairAttempt:
        return DoctorRepairAttempt(
            validation_passed=bool(request.head_sha), pr_url=request.swarmsy_pr_url, tests_run=request.tests_run, **kwargs,
        )

    def run_initial_repair(self, request: DoctorRequest) -> DoctorRepairAttempt:
        self._verify_target(request)
        self._redact_request(request)
        base_branch, base = self._repo()
        if self._head(request):
            raise PermissionError("A branch already exists without a validated Doctor delivery record.")
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
        if pr["state"] != "open" or pr["draft"]:
            raise PermissionError("The Doctor pull request must be open and ready for review.")
        findings = [comment.body for comment in actionable_comments]
        log(request, self.settings, f"codex_fix_cycle_{cycle}", "\n".join(findings), self.archive.upsert_request)
        self._stage(request, base=base, parent=request.head_sha, findings=findings)
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
        self._verify_pr(request, pr, request.head_sha, base_branch)
        if pr.get("merged") is True:
            self._record_merge(request, pr["merge_commit_sha"], base_branch)
            return self._attempt(request, merged=True)
        if pr["state"] != "open" or pr["draft"]:
            raise PermissionError("The Doctor pull request is closed or draft.")
        self._request_review(request)
        verdict, comments = self._codex_review(request)
        if verdict != "approved":
            return self._attempt(request, review_verdict=verdict, review_comments=comments,
                                 reason="Waiting for a completed Codex review of this exact commit.")
        if request.base_sha != base or pr["base"]["sha"] != base:
            raise PermissionError("Base advanced after Doctor validated this commit. Revalidate before merging.")
        passed, failures = self._ci_review(request.head_sha)
        if failures:
            return self._attempt(request, review_verdict="changes_requested", review_comments=failures,
                                 reason="Required GitHub CI checks requested follow-up.")
        if not request.learned_edits or any(edit.path in PROTECTED_FILES for edit in request.learned_edits):
            return self._attempt(request, review_verdict="approved", reason="Codex approved. Protected files require a manual merge.")
        ready = pr.get("mergeable") is True and pr.get("mergeable_state") == "clean" and passed
        return self._attempt(request, review_verdict="approved", merge_ready=ready,
                             reason="Codex approved. Waiting for required checks or repository merge policy.")

    def merge_pr(self, request: DoctorRequest, pr_url: str) -> bool:
        ready = self.poll_review(request)
        if ready.merged:
            return True
        if ready.review_verdict != "approved" or not ready.merge_ready:
            return False
        outcome = self.git.merge_pull_request(request.pr_number, head_sha=request.head_sha)
        if not outcome or outcome.get("merged") is not True:
            return False
        self._record_merge(request, outcome["sha"], request.base_branch)
        return True

    def _record_merge(self, request: DoctorRequest, commit: str, branch: str) -> None:
        request.merge_sha = sha(commit)
        request.base_branch = branch
        if self.deploy_workflow:
            request.deployment_workflow = self.deploy_workflow
            request.deployment_job = self.deploy_job
            request.deployment_status = "pending"
            request.deployment_reason = "Waiting for the target's Cloudflare deployment workflow."

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
