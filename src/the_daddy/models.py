from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CommandResult(BaseModel):
    returncode: int
    stdout: str
    stderr: str
    combined: str
    duration_seconds: float
    timed_out: bool = False


class FileSnapshot(BaseModel):
    path: str
    content: str


class PatchAction(BaseModel):
    path: str
    operation: Literal["replace_file", "regex_replace"]
    description: str = ""
    new_content: Optional[str] = None
    pattern: Optional[str] = None
    replacement: Optional[str] = None


class ArchitectureReview(BaseModel):
    diagnosis: str
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    backlog_items: List[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "medium"
    reviewed_at: str = Field(default_factory=utc_now_iso)


class DiagnosticPlan(BaseModel):
    diagnosis: str
    root_cause: str
    confidence: Literal["low", "medium", "high"]
    why_this_failed: List[str]
    changes: List[PatchAction] = Field(default_factory=list)
    post_fix_checks: List[str] = Field(default_factory=list)
    test_suggestions: List[str] = Field(default_factory=list)


class VetDecision(BaseModel):
    accepted: bool
    route: Literal["reject", "stage", "accept"]
    reason: str
    risk: Literal["low", "medium", "high"]
    reputation_delta: int = 0
    notes: List[str] = Field(default_factory=list)


class ExternalProposal(BaseModel):
    agent_id: str
    title: str
    summary: str
    proposed_changes: List[str] = Field(default_factory=list)
    payload: Dict = Field(default_factory=dict)
    submitted_at: str = Field(default_factory=utc_now_iso)


class RunRecord(BaseModel):
    run_id: str
    started_at: str = Field(default_factory=utc_now_iso)
    finished_at: Optional[str] = None
    command: str
    attempt_count: int = 0
    success: bool = False
    summary: str = ""
    architecture_review: Optional[ArchitectureReview] = None
    diagnostic_history: List[DiagnosticPlan] = Field(default_factory=list)
    patches_applied: List[Dict] = Field(default_factory=list)
    verification: Optional[CommandResult] = None
    trace: List[Dict] = Field(default_factory=list)
    backlog_updates: List[str] = Field(default_factory=list)


class AgentReputation(BaseModel):
    agent_id: str
    accepted_count: int = 0
    rejected_count: int = 0
    staged_count: int = 0
    trust_score: int = 50
    last_seen_at: str = Field(default_factory=utc_now_iso)

    def apply(self, route: str, delta: int) -> None:
        if route == "accept":
            self.accepted_count += 1
        elif route == "reject":
            self.rejected_count += 1
        else:
            self.staged_count += 1
        self.trust_score = max(0, min(100, self.trust_score + delta))
        self.last_seen_at = utc_now_iso()


class MemoryState(BaseModel):
    updated_at: str = Field(default_factory=utc_now_iso)
    architecture_reviews: List[ArchitectureReview] = Field(default_factory=list)
    run_index: List[str] = Field(default_factory=list)
    backlog: List[str] = Field(default_factory=list)
    accepted_improvements: List[str] = Field(default_factory=list)
    rejected_improvements: List[str] = Field(default_factory=list)
    failure_patterns: Dict[str, Dict] = Field(default_factory=dict)
    successful_fixes: Dict[str, List[Dict]] = Field(default_factory=dict)
    failed_fixes: Dict[str, List[Dict]] = Field(default_factory=dict)
    reputations: Dict[str, AgentReputation] = Field(default_factory=dict)
    quarantine_events: List[Dict] = Field(default_factory=list)
    metadata: Dict[str, str] = Field(default_factory=dict)
