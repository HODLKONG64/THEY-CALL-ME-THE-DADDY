from __future__ import annotations

import re
from urllib.parse import urlencode

from .config import _DADDY_REPO, _normalize_repo_slug
from .doctor_repair import scrub
from .swarmsy_doctor import DoctorReviewComment, is_moonboys_repo

REPAIR_LABEL = "doctor:repair-ci"
MERGE_LABEL = "doctor:merge-ci"
PAUSE_LABEL = "doctor:paused"
FAILED = {"failure", "timed_out"}


def audit_workflow(repo: str) -> str:
    if is_moonboys_repo(repo):
        return "full-linux-test-suite.yml"
    if _normalize_repo_slug(repo) == _normalize_repo_slug(_DADDY_REPO):
        return "swarmsy-doctor-queue.yml"
    return ""


def labels(pr: dict) -> set[str]:
    return {item["name"] for item in pr.get("labels", [])}


def paused(pr: dict) -> bool:
    return pr.get("draft") is True or PAUSE_LABEL in labels(pr)


def _failure_annotations(worker, job: dict) -> str:
    prefix = f"https://api.github.com/repos/{worker.git.github_repo}/check-runs/"
    match = re.fullmatch(re.escape(prefix) + r"([1-9][0-9]*)", job.get("check_run_url") or "", re.I)
    if not match:
        return ""
    try:
        annotations = worker._api("GET", f"check-runs/{match[1]}/annotations?per_page=10")
    except (OSError, RuntimeError):
        return ""
    if not isinstance(annotations, list):
        return ""
    lines = [
        scrub(f"{item.get('path', '')}:{item.get('start_line', '')}: {item.get('message', '')}", worker.settings)
        for item in annotations[:10]
        if isinstance(item, dict) and item.get("annotation_level") == "failure"
    ]
    return "\n".join(lines)[:1400]


def exact_ci(worker, commit: str, branch: str, *, merged: bool = False) -> tuple[str, str, list[DoctorReviewComment]]:
    endpoint = f"actions/workflows/{worker.ci_workflow}/runs"
    query = urlencode({"head_sha": commit, "branch": branch})
    events = {"push", "workflow_dispatch"} if merged else {"pull_request", "workflow_dispatch"}
    runs = worker._list(f"{endpoint}?{query}", list_key="workflow_runs")
    matching = [run for run in runs if run.get("head_sha") == commit
                and run.get("head_branch") == branch and run.get("event") in events]
    if not matching:
        return "missing", "", []
    run = max(matching, key=lambda item: int(item["id"]))
    run_id = int(run["id"])
    url = f"https://github.com/{worker.git.github_repo}/actions/runs/{run_id}"
    if run.get("status") != "completed":
        return "pending", url, []
    if run.get("conclusion") == "success":
        return "passed", url, []
    if run.get("conclusion") not in FAILED:
        return "interrupted", url, []

    jobs = worker._list(f"actions/runs/{run_id}/attempts/{int(run['run_attempt'])}/jobs", list_key="jobs")
    findings = []
    for job in jobs:
        if job.get("conclusion") not in FAILED or job.get("status") != "completed":
            continue
        steps = [step["name"] for step in job.get("steps", []) if step.get("conclusion") == "failure"]
        validation_steps = {
            "Run complete domain tests (no changed-file filtering)",
            "Run python -m pytest -q",
        }
        if not validation_steps.intersection(steps) or job.get("conclusion") != "failure":
            continue
        evidence = _failure_annotations(worker, job)
        findings.append(DoctorReviewComment(author="GitHub CI", body=(
            f"Test failure in {job['name']}: {', '.join(steps)}. "
            f"Attempt {run['run_attempt']}, {url}/job/{int(job['id'])}. "
            "Use the configured isolated test's output to diagnose the functional regression."
            + (f"\nGitHub failure annotations (diagnostic evidence):\n{evidence}" if evidence else "")
        )))
    return ("failed" if findings else "blocked"), url, findings
