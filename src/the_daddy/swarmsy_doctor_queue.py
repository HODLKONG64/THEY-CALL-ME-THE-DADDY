from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .swarmsy_doctor import (
    DoctorQueueConsumer,
    DoctorRequest,
    JsonDoctorArchive,
    NoopDoctorWorker,
    show_recent_daddy_repairs,
)

DADDY_REPO = "HODLKONG64/THEY-CALL-ME-THE-DADDY"
DEFAULT_ARCHIVE_FILE = "doctor_local/swarmsy_repair_archive.json"


def _parse_allowed_repos(value: str) -> set[str]:
    repos = {item.strip() for item in str(value or "").split(",") if item.strip()}
    if repos:
        return repos
    return {DADDY_REPO}


def _bool_from_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _archive_path() -> Path:
    raw = os.getenv("DADDY_DOCTOR_ARCHIVE_FILE", DEFAULT_ARCHIVE_FILE)
    return Path(raw).resolve()


def _queue_source_available(path: Path) -> bool:
    if os.getenv("DADDY_DOCTOR_ARCHIVE_FILE"):
        return True
    return path.exists()


def _parse_max_review_cycles(raw: str, default: int = 3) -> int:
    try:
        return max(1, int(str(raw or default)))
    except (TypeError, ValueError):
        return default


def _next_queued_request(archive: JsonDoctorArchive) -> DoctorRequest | None:
    queued = archive.list_queued_requests()
    if not queued:
        return None
    return queued[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process or query SWARMSY Doctor queue.")
    parser.add_argument("--process-once", action="store_true", help="Process one queued request.")
    parser.add_argument("--show-recent", action="store_true", help="Show recent archived repairs.")
    parser.add_argument("--limit", type=int, default=10, help="Recent repair limit for --show-recent.")
    args = parser.parse_args(argv)

    archive = JsonDoctorArchive(_archive_path())

    if args.show_recent:
        print(json.dumps(show_recent_daddy_repairs(archive, limit=args.limit), indent=2))
        return 0

    if not args.process_once:
        parser.print_help()
        return 2

    allowed_repos = _parse_allowed_repos(os.getenv("DADDY_ALLOWED_TARGET_REPOS", ""))
    auto_merge = _bool_from_env("DADDY_SWARMSY_AUTO_MERGE", default=False)
    max_cycles = _parse_max_review_cycles(os.getenv("DADDY_SWARMSY_REVIEW_MAX_CYCLES", "3"))

    if not _queue_source_available(archive.path):
        print(
            json.dumps(
                {
                    "status": "queue_source_unavailable",
                    "reason": "No hydrated Doctor queue source is configured for this checkout.",
                },
                indent=2,
            )
        )
        return 0

    queued_request = _next_queued_request(archive)
    if queued_request is None:
        print(json.dumps({"status": "no_queued_requests"}, indent=2))
        return 0

    worker = NoopDoctorWorker()
    if isinstance(worker, NoopDoctorWorker):
        print(
            json.dumps(
                {
                    "status": "worker_unavailable",
                    "request_id": queued_request.request_id,
                    "reason": "No real Doctor worker is configured; queued request was left unchanged.",
                },
                indent=2,
            )
        )
        return 0

    consumer = DoctorQueueConsumer(
        archive=archive,
        worker=worker,
        allowed_target_repos=allowed_repos,
        swarmsy_auto_merge=auto_merge,
        max_review_cycles=max_cycles,
    )
    result = consumer.process_request(queued_request)

    print(json.dumps(result.model_dump(mode="json"), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
