from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path

from .config import Settings, _DADDY_REPO, _normalize_repo_slug
from .doctor_ci import audit_workflow
from .doctor_repair import scrub
from .doctor_worker import GitHubDoctorWorker
from .doctor_history import HistoryIndex, repo_scope, shared_repo_scope
from .doctor_shared_lessons import sync_shared
from .doctor_diagnostics import report
from .git_tools import GitBranchExecutor
from .swarmsy_doctor import (
    SWARMSY_REPO,
    DoctorQueueConsumer,
    JsonDoctorArchive,
    archive_lock,
    create_doctor_request_from_plain_language,
    show_recent_daddy_repairs,
    utc_now_iso,
)

DEFAULT_ARCHIVE_FILE = "doctor_local/swarmsy_repair_archive.json"


def _watch_ci() -> bool:
    return os.getenv("DADDY_DOCTOR_WATCH_CI", "").lower() == "true"


def _max_review_cycles() -> int:
    try:
        return max(1, min(8, int(os.getenv("DADDY_SWARMSY_REVIEW_MAX_CYCLES", "3"))))
    except ValueError:
        return 3


def _worker(settings: Settings, archive: JsonDoctorArchive) -> GitHubDoctorWorker | None:
    image = os.getenv("DADDY_DOCTOR_VALIDATION_IMAGE", "").strip()
    command = os.getenv("DADDY_DOCTOR_TEST_COMMAND", "").strip()
    if not (settings.has_openai and settings.has_github and image and command and shutil.which("docker")):
        return None
    checks = {item.strip() for item in os.getenv("DADDY_DOCTOR_REQUIRED_CHECKS", "").split(",") if item.strip()}
    return GitHubDoctorWorker(
        settings, archive, validation_image=image, validation_command=command, required_checks=checks,
        deploy_workflow=os.getenv("DADDY_DOCTOR_CLOUDFLARE_WORKFLOW", "").strip(),
        deploy_job=os.getenv("DADDY_DOCTOR_CLOUDFLARE_JOB", "Cloudflare deploy").strip(),
        watch_ci=_watch_ci(),
        dispatch_ci=os.getenv("DADDY_DOCTOR_DISPATCH_CI", "").lower() == "true",
    )


def _process_once(archive: JsonDoctorArchive, settings: Settings, *, discover: bool = False) -> dict:
    if not archive.path.is_file():
        return {"status": "queue_source_unavailable", "reason": "Create or supply the persistent Doctor archive."}
    lock = archive.path.with_suffix(archive.path.suffix + ".process.lock")
    watch_ci = _watch_ci() and bool(audit_workflow(settings.github_repo))
    try:
        with archive_lock(lock, blocking=False):
            try:
                active = archive.active_requests(settings.github_repo, include_post_merge_ci=watch_ci)
            except ValueError:
                return {"status": "archive_invalid", "reason": "Doctor could not read the archive. Existing data was preserved."}
            if not active and not discover:
                return {"status": "no_queued_requests"}
            worker = _worker(settings, archive)
            if worker is None:
                return {
                    "status": "worker_unavailable", "request_id": active[0].request_id if active else "",
                    "reason": "Configure the OpenAI and GitHub credentials, target repo, and Docker validation image and test command.",
                }
            discovery = None
            if discover and worker.ci_workflow:
                try:
                    discovery = worker.discover_ci_repairs(enqueue=True)
                    active = archive.active_requests(settings.github_repo, include_post_merge_ci=watch_ci)
                except (RuntimeError, OSError, ValueError) as exc:
                    discovery = {"status": "scan_failed", "reason": scrub(str(exc), settings)[-500:]}
            if not active:
                return {"status": "no_queued_requests", **({"ci_scan": discovery} if discovery is not None else {})}
            request = active[0]
            if request.status == "merged":
                if request.deployment_status == "pending":
                    worker.poll_deployment(request)
                if watch_ci and request.post_merge_ci == "pending":
                    try:
                        worker.poll_merged_ci(request)
                    except (RuntimeError, OSError, ValueError) as exc:
                        request.post_merge_ci_reason = scrub(str(exc), settings)[-500:]
                        request.updated_at = utc_now_iso()
                        archive.upsert_request(request)
                result = request
            else:
                consumer = DoctorQueueConsumer(
                    archive=archive, worker=worker, allowed_target_repos=set(settings.allowed_target_repos),
                    swarmsy_auto_merge=settings.swarmsy_auto_merge, max_review_cycles=_max_review_cycles(),
                )
                result = consumer.process_request(request)
            return {
                "status": result.status, "request_id": result.request_id, "archive_id": result.archive_id,
                "pr_url": result.swarmsy_pr_url, "reason": scrub(result.final_reason, settings),
                "deployment_status": result.deployment_status, "deployment_url": result.deployment_url,
                "deployment_reason": scrub(result.deployment_reason, settings),
                "post_merge_ci": result.post_merge_ci, "post_merge_ci_url": result.post_merge_ci_url,
                "post_merge_ci_reason": scrub(result.post_merge_ci_reason, settings),
                **({"ci_scan": discovery} if discovery is not None else {}),
            }
    except BlockingIOError:
        return {"status": "worker_busy"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Submit, process, and track Doctor repairs.")
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--enqueue", metavar="PROBLEM", help="Queue a repair for the configured target.")
    operation.add_argument("--process-once", action="store_true", help="Process one request or review.")
    operation.add_argument("--watch", action="store_true", help="Continuously process requests and pending reviews.")
    operation.add_argument("--show-recent", action="store_true", help="Show recent archived repairs.")
    operation.add_argument("--sync-shared-memory", action="store_true", help="Synchronize terminal advisory lessons with private R2.")
    operation.add_argument("--sync-history", action="store_true", help="Index one historical GitHub page per approved read repository.")
    operation.add_argument("--scan-prs", action="store_true", help="Report recent open PRs and exact CI state without queuing repairs.")
    parser.add_argument("--allow-path", action="append", help="Narrow the request to a file or directory prefix ending in /.")
    parser.add_argument("--log-file", type=Path, help="Include the tail of a local diagnostic log.")
    parser.add_argument("--limit", type=int, default=10, help="Recent repair limit for --show-recent.")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between --watch polls.")
    args = parser.parse_args(argv)

    settings = Settings()
    archive = JsonDoctorArchive(Path(os.getenv("DADDY_DOCTOR_ARCHIVE_FILE", DEFAULT_ARCHIVE_FILE)).resolve())
    watch_ci = _watch_ci()
    if args.sync_shared_memory:
        if _normalize_repo_slug(settings.github_repo) not in settings.allowed_target_repos:
            parser.error("The configured target is outside DADDY_ALLOWED_TARGET_REPOS.")
        if not archive.path.is_file():
            parser.error("The persistent Doctor archive must exist.")
        repos = shared_repo_scope(settings.github_repo)
        index = HistoryIndex(archive.path.with_suffix(".history.sqlite3"), settings)
        try:
            with archive_lock(archive.path.with_suffix(".intelligence.lock"), blocking=False):
                result = sync_shared(index, settings, archive, settings.github_repo, repos)
        except BlockingIOError:
            result = {"status": "sync_busy"}
        except (RuntimeError, OSError, ValueError) as exc:
            print(json.dumps({"status": "shared_sync_failed", "reason": scrub(str(exc), settings)[:500]}))
            return 1
        print(json.dumps(result, indent=2))
        return 0
    if args.sync_history:
        if os.getenv("DADDY_DOCTOR_HISTORY_ENABLED", "").lower() != "true":
            parser.error("Enable DADDY_DOCTOR_HISTORY_ENABLED before indexing GitHub history.")
        if not settings.has_github:
            parser.error("Configure read access to GitHub and GITHUB_REPO.")
        if _normalize_repo_slug(settings.github_repo) not in settings.allowed_target_repos:
            parser.error("The configured target is outside DADDY_ALLOWED_TARGET_REPOS.")
        repos = repo_scope(os.getenv("DADDY_DOCTOR_HISTORY_REPOS", ""), settings.github_repo)
        git = GitBranchExecutor(github_token=settings.github_token, github_repo=settings.github_repo,
                                allowed_target_repos=settings.allowed_target_repos)
        index = HistoryIndex(archive.path.with_suffix(".history.sqlite3"), settings)
        def read_history(repo, endpoint):
            if repo not in repos:
                raise PermissionError("Repository is outside the history read scope.")
            return git._api_request("GET", f"https://api.github.com/repos/{repo}/{endpoint}")
        outcomes = []
        for repo in repos:
            try:
                outcomes.append(index.sync_page(repo, read_history))
            except (RuntimeError, OSError, ValueError) as exc:
                outcomes.append({"repo": repo, "error": scrub(str(exc), settings)[-500:]})
        print(json.dumps(outcomes, indent=2))
        return int(any("error" in outcome for outcome in outcomes))
    if args.scan_prs:
        worker = _worker(settings, archive)
        if worker is None or not worker.ci_workflow:
            parser.error("Configure the Doctor worker and enable DADDY_DOCTOR_WATCH_CI for the target.")
        print(json.dumps(worker.discover_ci_repairs(), indent=2))
        return 0
    if args.show_recent:
        rows = show_recent_daddy_repairs(archive, limit=args.limit)
        for row in rows:
            row["problem_summary"] = scrub(row["problem_summary"], settings)
            row["reason"] = scrub(row["reason"], settings)
            row["deployment_reason"] = scrub(row["deployment_reason"], settings)
            row["post_merge_ci_reason"] = scrub(row["post_merge_ci_reason"], settings)
        print(json.dumps(rows, indent=2))
        return 0
    if args.enqueue is not None:
        repo = settings.github_repo.strip() or _DADDY_REPO
        if _normalize_repo_slug(repo) not in settings.allowed_target_repos:
            parser.error("The configured target is outside DADDY_ALLOWED_TARGET_REPOS.")
        logs = []
        if args.log_file:
            with args.log_file.open("rb") as handle:
                handle.seek(max(0, args.log_file.stat().st_size - 16_000))
                logs = [scrub(handle.read(16_000).decode(errors="replace"), settings)]
        request, _ = create_doctor_request_from_plain_language(
            scrub(args.enqueue, settings), repo_target=repo, allowed_paths=args.allow_path, logs=logs,
        )
        if _normalize_repo_slug(repo) != _normalize_repo_slug(SWARMSY_REPO):
            request.source = "daddy"
        archive.upsert_request(request)
        print(json.dumps({"status": "queued", "request_id": request.request_id, "archive_id": request.archive_id}))
        return 0
    if args.process_once:
        print(json.dumps(_process_once(archive, settings, discover=watch_ci), indent=2))
        return 0
    previous = None
    next_scan = 0.0
    try:
        while True:
            discover = watch_ci and time.monotonic() >= next_scan
            if discover:
                next_scan = time.monotonic() + 300
            result = _process_once(archive, settings, discover=discover)
            if result != previous:
                print(json.dumps(result), flush=True)
                previous = result
            time.sleep(max(15, args.interval))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
