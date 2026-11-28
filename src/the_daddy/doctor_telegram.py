"""Doctor's private Telegram approval transport. No raw logs, code or credentials in notices."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

import httpx

from .swarmsy_doctor import DoctorRequest

URL = "https://api.cryptomoonboys.com/internal/doctor-approvals"
TELEGRAM_EVENTS = {
    "failed_with_reason", "blocked_needs_human_permission", "merged",
    "deployment_deployed", "deployment_failed", "post_merge_needs_review",
    "post_merge_follow_up_queued",
    "live_review_passed", "live_review_needs_review", "live_review_rollback_queued",
}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True).encode()).hexdigest()


class TelegramApproval:
    def __init__(self, archive_path: Path, enabled: bool) -> None:
        self.enabled = enabled
        self.token = os.getenv("DOCTOR_APPROVAL_TOKEN", "")
        self.path = archive_path.with_suffix(".telegram.sqlite3")

    def _post(self, payload: dict) -> dict:
        if not self.enabled or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", self.token):
            return {}
        try:
            with httpx.Client(timeout=httpx.Timeout(12, connect=4), trust_env=False,
                              follow_redirects=False) as client:
                response = client.post(URL, headers={"X-Doctor-Approval-Token": self.token, "User-Agent": "Moonboys-Doctor/1.0"}, json=payload)
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, dict) else {}
        except (httpx.HTTPError, ValueError):
            return {}

    @staticmethod
    def identity(request: DoctorRequest) -> dict:
        repo = request.repo_target.lower()
        return {"repo": repo, "job_key": digest([repo, request.request_id]),
                "pr_number": request.pr_number, "head_sha": request.head_sha, "base_sha": request.base_sha}

    def approval(self, request: DoctorRequest, action: str = "read", *, allow_auto: bool = False) -> tuple[str, str]:
        identity = self.identity(request)
        if not request.pr_number or not all(re.fullmatch(r"[a-f0-9]{40}", identity[k]) for k in ("head_sha", "base_sha")):
            return "unavailable", ""
        payload = {"action": action, **identity}
        if action == "ready" and allow_auto:
            payload["allow_auto"] = True
        response = self._post(payload)
        state = response.get("state")
        if state == "missing":
            return "missing", ""
        if (response.get("head_sha") != request.head_sha or response.get("base_sha") != request.base_sha
                or type(response.get("revision")) is not int):
            return "unavailable", ""
        if state not in {"ready", "approved", "rejected", "fix_requested", "invalidated", "merged"}:
            return "unavailable", ""
        return state, "auto" if response.get("decision_mode") == "auto" else "manual"

    def decision(self, request: DoctorRequest, action: str = "read", *, allow_auto: bool = False) -> str:
        return self.approval(request, action, allow_auto=allow_auto)[0]

    def _db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("CREATE TABLE IF NOT EXISTS outbox (event_key TEXT PRIMARY KEY, payload TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0)")
        db.execute("CREATE TABLE IF NOT EXISTS merge_receipts (receipt_key TEXT PRIMARY KEY, payload TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0)")
        return db

    def record_merge(self, request: DoctorRequest) -> None:
        if not self.enabled or not request.pr_number or not all(
            re.fullmatch(r"[a-f0-9]{40}", commit)
            for commit in (request.head_sha, request.base_sha, request.merge_sha)
        ):
            return
        payload = {"action": "merged", **self.identity(request), "merge_sha": request.merge_sha}
        try:
            db = self._db()
            try:
                with db:
                    db.execute("INSERT OR IGNORE INTO merge_receipts(receipt_key,payload) VALUES(?,?)",
                               (digest(payload), json.dumps(payload)))
            finally:
                db.close()
        except (OSError, sqlite3.Error):
            return

    def emit(self, request: DoctorRequest, event: str, discriminator: str = "") -> None:
        if not self.enabled or event not in TELEGRAM_EVENTS:
            return
        identity = self.identity(request)
        key = digest([identity["job_key"], request.head_sha, event, discriminator])
        payload = {"action": "event", "event_key": key, "event": event, "repo": identity["repo"],
                   "pr_number": request.pr_number, "head_sha": request.head_sha}
        try:
            db = self._db()
            try:
                with db:
                    db.execute("INSERT OR IGNORE INTO outbox(event_key,payload) VALUES(?,?)", (key, json.dumps(payload)))
            finally:
                db.close()
        except (OSError, sqlite3.Error):
            # Reporting is advisory; merge approval always fails closed independently.
            return

    def report(self, request: DoctorRequest) -> None:
        self.emit(request, request.status)
        if request.deployment_status in ("deployed", "failed"):
            self.emit(request, "deployment_" + request.deployment_status, request.merge_sha)
        if request.post_merge_ci in ("passed", "needs_review", "follow_up_queued"):
            self.emit(request, "post_merge_" + request.post_merge_ci, request.merge_sha)
        if request.live_review_status in ("passed", "needs_review", "rollback_queued"):
            self.emit(request, "live_review_" + request.live_review_status, request.merge_sha)
        if request.status == "merged" and not request.rollback_of:
            self.record_merge(request)

    def flush(self) -> None:
        if not self.enabled or not self.token:
            return
        try:
            db = self._db()
            try:
                for key, raw in db.execute("SELECT receipt_key,payload FROM merge_receipts WHERE sent=0 ORDER BY attempts,rowid LIMIT 8").fetchall():
                    receipt = json.loads(raw)
                    response = self._post(receipt)
                    recorded = response.get("state") == "merged" and all(
                        response.get(field) == receipt[field] for field in ("head_sha", "base_sha", "merge_sha")
                    )
                    terminal = response.get("state") in {"missing", "rejected", "fix_requested", "invalidated"}
                    with db:
                        db.execute("UPDATE merge_receipts SET sent=?,attempts=attempts+1 WHERE receipt_key=?",
                                   (int(recorded or terminal), key))
                for key, raw in db.execute("SELECT event_key,payload FROM outbox WHERE sent=0 ORDER BY rowid LIMIT 8").fetchall():
                    if self._post(json.loads(raw)).get("ok") is not True:
                        break
                    with db:
                        db.execute("UPDATE outbox SET sent=1 WHERE event_key=?", (key,))
            finally:
                db.close()
            self._post({"action": "flush"})
        except (OSError, sqlite3.Error, ValueError):
            return
