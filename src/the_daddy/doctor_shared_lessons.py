"""Optional shared, advisory-only repair lessons in a dedicated private R2 bucket.

Never replicate live queue state, credentials, raw logs or executable edits.
Immutable content-addressed objects tolerate concurrent writers; importing
them cannot grant repair authority or satisfy a validation/merge gate.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from urllib.parse import urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .doctor_history import similarity, query_text
from .doctor_repair import scrub
from .swarmsy_doctor import FINAL_STATUSES

PREFIX = "doctor-intelligence/v1/"
MAX_BYTES = 16384
LIMIT = 25
HEX = re.compile(r"[0-9a-f]{64}")
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)")
STATES = FINAL_STATUSES


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encode(record: dict) -> bytes:
    return json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def terminal_lesson(past, settings) -> dict:
    return {
        "version": 1,
        "repo": past.repo_target.casefold(),
        "case": digest(past.request_id.encode()),
        "updated": past.updated_at,
        "problem": scrub(past.problem_summary, settings)[:500],
        "outcome": past.status,
        "reason": scrub(past.final_reason, settings)[:800],
        "post_merge_ci": past.post_merge_ci,
        "deployment_job": past.deployment_status,
        "pr": past.pr_number,
        "head_sha": past.head_sha if re.fullmatch(r"[0-9a-f]{40}", past.head_sha) else "",
        "merge_sha": past.merge_sha if re.fullmatch(r"[0-9a-f]{40}", past.merge_sha) else "",
        "lessons": [
            scrub(row.get("detail", ""), settings)[:300]
            for row in past.repair_log[-8:]
            if row.get("event") in {"patch_rejected", "api_blocked", "api_approved"}
        ][-3:],
    }


def object_key(record: dict, raw: bytes) -> str:
    return f"{PREFIX}{record['repo']}/{record['case']}/{digest(raw)}.json"


def parse_lesson(key: str, raw: bytes, repo: str, settings) -> dict:
    if len(raw) > MAX_BYTES:
        raise ValueError("Shared lesson exceeds size limit.")
    record = json.loads(raw)
    if not isinstance(record, dict) or set(record) != {
        "version", "repo", "case", "updated", "problem", "outcome", "reason",
        "post_merge_ci", "deployment_job", "pr", "head_sha", "merge_sha", "lessons"
    }:
        raise ValueError("Invalid shared lesson schema.")
    if (record["version"] != 1 or record["repo"] != repo
            or not isinstance(record["case"], str) or not HEX.fullmatch(record["case"])
            or not isinstance(record["updated"], str) or not STAMP.fullmatch(record["updated"])
            or record["outcome"] not in STATES
            or record["post_merge_ci"] not in {"unconfigured", "pending", "passed", "follow_up_queued", "needs_review"}
            or record["deployment_job"] not in {"unconfigured", "pending", "deployed", "failed"}
            or type(record["pr"]) is not int or record["pr"] < 0
            or any(not isinstance(record[field], str) or (record[field] and not re.fullmatch(r"[0-9a-f]{40}", record[field]))
                   for field in ("head_sha", "merge_sha"))
            or not isinstance(record["lessons"], list) or len(record["lessons"]) > 3
            or not all(isinstance(x, str) for x in [record["problem"], record["reason"], *record["lessons"]])
            or object_key(record, raw) != key):
        raise ValueError("Invalid shared lesson identity or outcome.")
    record["problem"] = scrub(record["problem"], settings)[:500]
    record["reason"] = scrub(record["reason"], settings)[:800]
    record["lessons"] = [scrub(item, settings)[:300] for item in record["lessons"]]
    return record


class SharedLessons:
    def __init__(self, index, settings, client=None) -> None:
        self.index, self.settings = index, settings
        self.bucket = os.getenv("DADDY_DOCTOR_INTELLIGENCE_BUCKET", "").strip()
        if not self.bucket or self.bucket == settings.r2_bucket:
            raise ValueError("Configure a dedicated private Doctor intelligence bucket, separate from legacy R2 memory.")
        endpoint = urlsplit(settings.r2_endpoint_url)
        if (endpoint.scheme != "https" or not (endpoint.hostname or "").endswith(".r2.cloudflarestorage.com")
                or endpoint.username or endpoint.password or endpoint.path not in ("", "/")
                or endpoint.query or endpoint.fragment or endpoint.port not in (None, 443)):
            raise ValueError("Doctor intelligence requires the account's HTTPS R2 S3 endpoint.")
        access_key = os.getenv("DADDY_DOCTOR_INTELLIGENCE_R2_ACCESS_KEY_ID", "")
        secret_key = os.getenv("DADDY_DOCTOR_INTELLIGENCE_R2_SECRET_ACCESS_KEY", "")
        if not access_key or not secret_key:
            raise ValueError("Configure bucket-scoped R2 credentials.")
        self.client = client if client is not None else boto3.client(
            "s3", endpoint_url=settings.r2_endpoint_url, aws_access_key_id=access_key,
            aws_secret_access_key=secret_key, region_name=settings.r2_region,
            config=Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 2}),
        )

    def _db(self):
        db = self.index.connect()
        with db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS shared_seen (key TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS shared_cursor (repo TEXT PRIMARY KEY, last_key TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS shared_latest (
                    repo TEXT NOT NULL, case_id TEXT NOT NULL, updated TEXT NOT NULL,
                    key TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(repo,case_id)
                );
            """)
        return db

    @staticmethod
    def _remember(db, key, record):
        db.execute("INSERT OR IGNORE INTO shared_seen VALUES(?)", (key,))
        db.execute("""INSERT INTO shared_latest VALUES(?,?,?,?,?)
                      ON CONFLICT(repo,case_id) DO UPDATE SET updated=excluded.updated,
                      key=excluded.key,record=excluded.record
                      WHERE (excluded.updated,excluded.key) > (shared_latest.updated,shared_latest.key)""",
                   (record["repo"], record["case"], record["updated"], key, json.dumps(record)))

    def sync(self, archive, target: str, repos: tuple[str, ...]) -> dict:
        db = self._db()
        uploaded = downloaded = 0
        try:
            # Only the configured target's terminal records may be exported.
            for past in sorted(archive.all_requests(), key=lambda p: p.updated_at):
                if past.repo_target.casefold() != target.casefold() or past.status not in FINAL_STATUSES:
                    continue
                record = terminal_lesson(past, self.settings)
                raw = encode(record)
                key = object_key(record, raw)
                if db.execute("SELECT 1 FROM shared_seen WHERE key=?", (key,)).fetchone():
                    continue
                record = parse_lesson(key, raw, target.casefold(), self.settings)
                self.client.put_object(Bucket=self.bucket, Key=key, Body=raw, ContentType="application/json")
                with db:
                    self._remember(db, key, record)
                uploaded += 1
                if uploaded >= LIMIT:
                    break
            # A bounded page per repository; cursor loops so late inserts are discovered.
            for repo in repos:
                prefix = PREFIX + repo + "/"
                cursor = db.execute("SELECT last_key FROM shared_cursor WHERE repo=?", (repo,)).fetchone()
                args = {"Bucket": self.bucket, "Prefix": prefix, "MaxKeys": LIMIT}
                if cursor and cursor[0]:
                    args["StartAfter"] = cursor[0]
                page = self.client.list_objects_v2(**args)
                keys = page.get("Contents", [])
                if not isinstance(keys, list) or len(keys) > LIMIT:
                    raise ValueError("Invalid shared lesson listing.")
                last = ""
                for item in keys:
                    key = item.get("Key", "")
                    if not key.startswith(prefix):
                        raise ValueError("Unexpected shared lesson prefix.")
                    last = key
                    if db.execute("SELECT 1 FROM shared_seen WHERE key=?", (key,)).fetchone():
                        continue
                    if not 0 < item.get("Size", 0) <= MAX_BYTES:
                        continue
                    body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
                    try:
                        raw = body.read(MAX_BYTES + 1)
                    finally:
                        body.close()
                    try:
                        record = parse_lesson(key, raw, repo, self.settings)
                    except (ValueError, TypeError, KeyError):
                        continue
                    with db:
                        self._remember(db, key, record)
                    downloaded += 1
                with db:
                    db.execute("INSERT OR REPLACE INTO shared_cursor VALUES(?,?)",
                               (repo, last if page.get("IsTruncated") else ""))
            return {"uploaded": uploaded, "downloaded": downloaded}
        finally:
            db.close()


def shared_search(index, settings, request, repos: tuple[str, ...]) -> list[dict]:
    db = index.connect()
    try:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='shared_latest'").fetchone():
            return []
        query = query_text(request, settings)
        ranked = []
        for repo in repos:
            for (raw,) in db.execute("SELECT record FROM shared_latest WHERE repo=?", (repo,)):
                record = json.loads(raw)
                if record["case"] == digest(request.request_id.encode()):
                    continue
                score = max(similarity(query, record["problem"]), similarity(request.problem_summary, record["problem"]))
                if score >= 0.25:
                    ranked.append((score, record["updated"], record["case"], record))
        ranked.sort(key=lambda item: item[:3], reverse=True)
        return [{"source": "shared_doctor_advisory", "similarity": round(score, 3), **record}
                for score, _, _, record in ranked[:5]]
    finally:
        db.close()


def sync_shared(index, settings, archive, target, repos):
    try:
        return SharedLessons(index, settings).sync(archive, target, repos)
    except (BotoCoreError, ClientError):
        # Avoid including provider exception payloads or signed requests in logs.
        raise RuntimeError("Private R2 intelligence synchronization failed.") from None
