from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .swarmsy_doctor import (
    DoctorQueueConsumer,
    JsonDoctorArchive,
    NoopDoctorWorker,
    show_recent_daddy_repairs,
)


def _parse_allowed_repos(value: str) -> set[str]:
    repos = {item.strip() for item in str(value or "").split(",") if item.strip()}
    if repos:
        return repos
    return {"HODLKONG64/THEY-CALL-ME-THE-DADDY", "HODLKONG64/SWARMSY"}


def _bool_from_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _archive_path() -> Path:
    raw = os.getenv("DADDY_DOCTOR_ARCHIVE_FILE", "doctor_local/swarmsy_repair_archive.json")
    return Path(raw).resolve()


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
    max_cycles = int(os.getenv("DADDY_SWARMSY_REVIEW_MAX_CYCLES", "3"))

    consumer = DoctorQueueConsumer(
        archive=archive,
        worker=NoopDoctorWorker(),
        allowed_target_repos=allowed_repos,
        swarmsy_auto_merge=auto_merge,
        max_review_cycles=max_cycles,
    )
    result = consumer.process_next()

    if result is None:
        print(json.dumps({"status": "no_queued_requests"}, indent=2))
        return 0

    print(json.dumps(result.model_dump(mode="json"), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
