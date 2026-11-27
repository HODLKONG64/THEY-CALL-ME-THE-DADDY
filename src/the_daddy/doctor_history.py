"""Bounded, read-only repair intelligence. Historical material is never authority."""
from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from .doctor_repair import scrub
from .git_tools import GITHUB_REPO_SLUG
from .swarmsy_doctor import FINAL_STATUSES, DoctorRequest

STOP = set("a an and are as at be by can do for from has have in is it of on or pr repair fix the to was with".split())
SHA = re.compile(r"[0-9a-f]{40}")
PAGE_SIZE = 100
SCHEMA = 1


def terms(value: str) -> set[str]:
    return {word for word in re.findall(r"[a-z][a-z0-9_-]{2,}", value.casefold()[:16000])
            if word not in STOP and not word.startswith("redacted")}


def similarity(left: str, right: str) -> float:
    a, b = terms(left), terms(right)
    if not a or not b:
        return 0.0
    return len(a & b) / (len(a) * len(b)) ** 0.5


def repo_scope(value: str, target: str) -> tuple[str, ...]:
    """Separate explicit read allowlist; never changes the write allowlist."""
    repos = {target.casefold(), *(item.strip().casefold() for item in value.split(",") if item.strip())}
    if len(repos) > 12 or any(not GITHUB_REPO_SLUG.fullmatch(repo)
                              or repo.split("/")[1] in {".", ".."} for repo in repos):
        raise ValueError("Invalid Doctor history repository scope.")
    return tuple(sorted(repos))


def shared_repo_scope(target: str) -> tuple[str, ...]:
    """Separate advisory sharing from GitHub API access; legacy default is unchanged."""
    configured = os.getenv("DADDY_DOCTOR_SHARED_REPOS")
    if configured is None:
        configured = os.getenv("DADDY_DOCTOR_HISTORY_REPOS", "")
    return repo_scope(configured, target)


def query_text(request: DoctorRequest, settings) -> str:
    return scrub(" ".join([request.problem_summary, request.feature_hint, *request.allowed_paths,
                           *request.logs[-3:]]), settings)[:12000]


def local_lessons(request: DoctorRequest, archive, settings) -> list[dict]:
    query = query_text(request, settings)
    ranked = []
    for past in archive.all_requests():
        if (past.request_id == request.request_id or past.status not in FINAL_STATUSES
                or past.repo_target.casefold() != request.repo_target.casefold()):
            continue
        score = max(similarity(query, past.problem_summary),
                    similarity(request.problem_summary, past.problem_summary))
        if score < 0.25:
            continue
        ranked.append((score, past.updated_at, past))
    results = []
    for score, _, past in sorted(ranked, key=lambda item: (item[0], item[1]), reverse=True)[:5]:
        results.append({
            "source": "local_doctor_archive",
            "reference": scrub(past.swarmsy_pr_url, settings)[:250],
            "similarity": round(score, 3),
            "problem": scrub(past.problem_summary, settings)[:500],
            "outcome": past.status,
            "post_merge_ci": past.post_merge_ci,
            "deployment_job": past.deployment_status,
            "reason": scrub(past.final_reason, settings)[:800],
            "lessons": [{"event": scrub(row.get("event", ""), settings)[:60],
                         "detail": scrub(row.get("detail", ""), settings)[:400]}
                        for row in past.repair_log[-8:]
                        if row.get("event") in {"patch_rejected", "validation", "api_approved", "api_blocked"}][-3:],
        })
    return results


class HistoryIndex:
    """SQLite index outside Git; GitHub is the historical source of truth.

    Ingestion is resumable, idempotent and read-only. Reconciliation uses a
    two-day overlap and periodically restarts the full scan to recover from
    pagination changes. Never treat a closed issue as a verified solution.
    """
    def __init__(self, path: Path, settings) -> None:
        self.path = path
        self.settings = settings

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Create with owner-only permissions; the parent must be service-private.
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA busy_timeout=10000")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA):
                raise ValueError("Unsupported Doctor history index schema.")
            db.executescript("""
              CREATE TABLE IF NOT EXISTS history (
                repo TEXT NOT NULL, number INTEGER NOT NULL, kind TEXT NOT NULL,
                state TEXT NOT NULL, updated TEXT NOT NULL, title TEXT NOT NULL,
                body TEXT NOT NULL, PRIMARY KEY(repo, number)
              );
              CREATE TABLE IF NOT EXISTS checkpoint (
                repo TEXT PRIMARY KEY, page INTEGER NOT NULL, since TEXT NOT NULL,
                started TEXT NOT NULL, full_scan TEXT NOT NULL
              );
              PRAGMA user_version=1;
            """)
            return db
        except BaseException:
            db.close()
            raise

    def sync_page(self, repo: str, api) -> dict:
        """Process one page; checkpoint commits only after successful ingestion."""
        now = datetime.now(timezone.utc)
        stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        db = self.connect()
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT page,since,started,full_scan FROM checkpoint WHERE repo=?",
                                 (repo,)).fetchone()
                page, since, started, full_scan = row or (1, "", stamp, stamp)
                if page == 1 and since and now - datetime.fromisoformat(full_scan) >= timedelta(days=30):
                    since, started, full_scan = "", stamp, stamp
                params = {"state": "all", "sort": "updated", "direction": "asc",
                          "page": page, "per_page": PAGE_SIZE}
                if since:
                    params["since"] = since
                batch = api(repo, "issues?" + urlencode(params))
                if not isinstance(batch, list) or len(batch) > PAGE_SIZE:
                    raise ValueError("Incomplete GitHub history response.")
                for item in batch:
                    if not isinstance(item, dict):
                        raise ValueError("Invalid GitHub history item.")
                    number, updated = item.get("number"), item.get("updated_at")
                    if not isinstance(number, int) or number < 1 or not isinstance(updated, str):
                        raise ValueError("Missing GitHub history identity.")
                    # Only sanitized, bounded metadata; no raw logs, patches or attachments.
                    db.execute("""INSERT INTO history VALUES(?,?,?,?,?,?,?)
                        ON CONFLICT(repo,number) DO UPDATE SET
                        kind=excluded.kind,state=excluded.state,updated=excluded.updated,
                        title=excluded.title,body=excluded.body
                        WHERE excluded.updated >= history.updated""",
                        (repo, number, "pr" if "pull_request" in item else "issue",
                         "closed" if item.get("state") == "closed" else "open", updated,
                         scrub(str(item.get("title") or ""), self.settings)[:500],
                         scrub(str(item.get("body") or ""), self.settings)[:4000]))
                complete = len(batch) < PAGE_SIZE
                if complete:
                    overlap = datetime.fromisoformat(started) - timedelta(days=2)
                    page, since, started = 1, overlap.strftime("%Y-%m-%dT%H:%M:%SZ"), stamp
                else:
                    page += 1
                db.execute("INSERT OR REPLACE INTO checkpoint VALUES(?,?,?,?,?)",
                           (repo, page, since, started, full_scan))
            return {"repo": repo, "indexed": len(batch), "cycle_complete": complete, "next_page": page}
        finally:
            db.close()

    def search(self, request: DoctorRequest, repos: tuple[str, ...], api) -> list[dict]:
        query = query_text(request, self.settings)
        db = self.connect()
        try:
            placeholders = ",".join("?" for _ in repos)
            rows = db.execute(f"""SELECT repo,number,kind,state,updated,title,body FROM history
                               WHERE repo IN ({placeholders}) AND state='closed'""", repos)
            ranked = []
            for repo, number, kind, state, updated, title, body in rows:
                score = max(similarity(request.problem_summary, title), similarity(query, title + " " + body))
                if score >= 0.25:
                    ranked.append((score, updated, repo, number, kind, title, body))
            ranked.sort(reverse=True)
        finally:
            db.close()
        results = []
        for score, _, repo, number, kind, title, body in ranked[:5]:
            evidence = {"source": "github_history", "repo": repo, "number": number,
                        "kind": kind, "similarity": round(score, 3), "title": title,
                        "summary": body[:1200], "outcome": "closed_not_verified",
                        "url": f"https://github.com/{repo}/{'pull' if kind == 'pr' else 'issues'}/{number}"}
            try:
                if kind == "pr":
                    detail = api(repo, f"pulls/{number}")
                    if isinstance(detail, dict) and detail.get("merged") is True:
                        evidence["outcome"] = "merged_not_production_verified"
                        files = api(repo, f"pulls/{number}/files?per_page=20")
                        if isinstance(files, list):
                            evidence["files"] = [scrub(str(f.get("filename") or ""), self.settings)[:180]
                                                 for f in files[:20] if isinstance(f, dict)]
                        reviews = api(repo, f"pulls/{number}/reviews?per_page=10")
                        if isinstance(reviews, list):
                            evidence["review_notes"] = [scrub(str(f.get("body") or ""), self.settings)[:400]
                                                        for f in reviews[:10] if isinstance(f, dict) and f.get("body")][:3]
                comments = api(repo, f"issues/{number}/comments?per_page=10")
                if isinstance(comments, list):
                    evidence["comments"] = [scrub(str(f.get("body") or ""), self.settings)[:400]
                                            for f in comments[:10] if isinstance(f, dict) and f.get("body")][:3]
            except (RuntimeError, OSError, ValueError):
                evidence["details_unavailable"] = True
            results.append(evidence)
        return results
