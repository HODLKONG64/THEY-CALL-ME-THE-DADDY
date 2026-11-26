from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path

from .config import Settings, _DADDY_REPO, _normalize_repo_slug
from .doctor_repair import scrub
from .doctor_worker import GitHubDoctorWorker
from .swarmsy_doctor import (
    SWARMSY_REPO,
    DoctorQueueConsumer,
    JsonDoctorArchive,
    archive_lock,
    create_doctor_request_from_plain_language,
    show_recent_daddy_repairs,
)

DEFAULT_ARCHIVE_FILE = "doctor_local/swarmsy_repair_archive.json"


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
    )


def _process_once(archive: JsonDoctorArchive, settings: Settings) -> dict:
    if not archive.path.is_file():
        return {"status": "queue_source_unavailable", "reason": "Create or supply the persistent Doctor archive."}
    lock = archive.path.with_suffix(archive.path.suffix + ".process.lock")
    try:
        with archive_lock(lock, blocking=False):
            try:
                active = archive.active_requests(settings.github_repo)
            except ValueError:
                return {"status": "archive_invalid", "reason": "Doctor could not read the archive. Existing data was preserved."}
            if not active:
                return {"status": "no_queued_requests"}
            request = active[0]
            worker = _worker(settings, archive)
            if worker is None:
                return {
                    "status": "worker_unavailable", "request_id": request.request_id,
                    "reason": "Configure the OpenAI and GitHub credentials, target repo, and Docker validation image and test command.",
                }
            if request.status == "merged":
                worker.poll_deployment(request)
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
    parser.add_argument("--allow-path", action="append", help="Narrow the request to a file or directory prefix ending in /.")
    parser.add_argument("--log-file", type=Path, help="Include the tail of a local diagnostic log.")
    parser.add_argument("--limit", type=int, default=10, help="Recent repair limit for --show-recent.")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between --watch polls.")
    args = parser.parse_args(argv)

    settings = Settings()
    archive = JsonDoctorArchive(Path(os.getenv("DADDY_DOCTOR_ARCHIVE_FILE", DEFAULT_ARCHIVE_FILE)).resolve())
    if args.show_recent:
        rows = show_recent_daddy_repairs(archive, limit=args.limit)
        for row in rows:
            row["problem_summary"] = scrub(row["problem_summary"], settings)
            row["reason"] = scrub(row["reason"], settings)
            row["deployment_reason"] = scrub(row["deployment_reason"], settings)
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
        print(json.dumps(_process_once(archive, settings), indent=2))
        return 0
    previous = None
    while True:
        result = _process_once(archive, settings)
        if result != previous:
            print(json.dumps(result), flush=True)
            previous = result
        time.sleep(max(15, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
