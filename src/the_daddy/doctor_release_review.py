"""Persist Brain's verdict independently of the Doctor queue archive."""

import sqlite3
from pathlib import Path
from typing import Literal

from .doctor_repair import sha
from .swarmsy_doctor import DoctorRequest

BrainVerdict = Literal["approved", "changes_requested"]


class BrainReviewStore:
    def __init__(self, archive_path: Path) -> None:
        self.path = archive_path.with_suffix(".brain-review.sqlite3")

    def _identity(self, request: DoctorRequest) -> tuple[str, str, int, str, str]:
        if request.pr_number < 1:
            raise ValueError("A Brain verdict requires an existing pull request.")
        return (
            request.repo_target.lower(), request.request_id, request.pr_number,
            sha(request.head_sha), sha(request.base_sha),
        )

    def read(self, request: DoctorRequest) -> tuple[str, str]:
        if not self.path.is_file():
            return "pending", ""
        try:
            with sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=3) as connection:
                row = connection.execute(
                    "SELECT verdict, reason FROM reviews WHERE repo=? AND request_id=? AND pr=? AND head=? AND base=?",
                    self._identity(request),
                ).fetchone()
        except sqlite3.OperationalError:
            return "pending", ""
        return row or ("pending", "")

    def record(self, request: DoctorRequest, verdict: BrainVerdict, reason: str) -> None:
        if verdict not in ("approved", "changes_requested") or not reason.strip():
            raise ValueError("Invalid Brain review verdict.")
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS reviews (
                    repo TEXT NOT NULL, request_id TEXT NOT NULL, pr INTEGER NOT NULL,
                    head TEXT NOT NULL, base TEXT NOT NULL, verdict TEXT NOT NULL,
                    reason TEXT NOT NULL, PRIMARY KEY (repo, request_id, pr, head, base)
                )
            """)
            connection.execute(
                "INSERT OR IGNORE INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?)",
                (*self._identity(request), verdict, reason[:1000]),
            )
