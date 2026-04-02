from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PatchAction(BaseModel):
    path: str
    operation: Literal["replace_file", "regex_replace"]
    new_content: str | None = None
    pattern: str | None = None
    replacement: str | None = None
    description: str = ""


class SelfEvolutionAction(BaseModel):
    title: str
    description: str
    risk: Literal["safe", "branch", "recommend"] = "safe"
    patches: list[PatchAction] = Field(default_factory=list)


class ArchitectureReview(BaseModel):
    diagnosis: str
    system_intent: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    backlog_items: list[str] = Field(default_factory=list)
    self_evolution_actions: list[SelfEvolutionAction] = Field(default_factory=list)
    execution_notes: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "medium"
    reviewed_at: str = Field(default_factory=utc_now_iso)


class DiagnosticPlan(BaseModel):
    diagnosis: str
    root_cause: str
    confidence: Literal["low", "medium", "high"]
    why_this_failed: list[str] = Field(default_factory=list)
    changes: list[PatchAction] = Field(default_factory=list)
    post_fix_checks: list[str] = Field(default_factory=list)


class CommandResult(BaseModel):
    returncode: int
    stdout: str
    stderr: str
    combined: str
    duration_seconds: float
    timed_out: bool = False


class SelfEvolutionRecord(BaseModel):
    enabled: bool
    attempted: bool
    applied: bool
    route: str
    summary: str
    reasons: list[str] = Field(default_factory=list)
    proposed_count: int = 0
    applied_count: int = 0
    patches: list[dict[str, Any]] = Field(default_factory=list)


class RunRecord(BaseModel):
    run_id: str
    started_at: str = Field(default_factory=utc_now_iso)
    finished_at: str | None = None
    command: str
    attempt_count: int = 0
    success: bool = False
    summary: str = ""
    architecture_review: ArchitectureReview | None = None
    self_evolution: SelfEvolutionRecord | None = None
    diagnostic_history: list[DiagnosticPlan] = Field(default_factory=list)
    patches_applied: list[dict[str, Any]] = Field(default_factory=list)
    verification: CommandResult | None = None
    trace: list[dict[str, Any]] = Field(default_factory=list)
    backlog_updates: list[str] = Field(default_factory=list)
    repo_fingerprint: dict[str, Any] = Field(default_factory=dict)
    rollback_manifest: list[dict[str, Any]] = Field(default_factory=list)


class ReputationRecord(BaseModel):
    agent_id: str
    score: int = 0
    accepted: int = 0
    rejected: int = 0
    total: int = 0


class VetDecision(BaseModel):
    accepted: bool
    route: Literal["safe", "branch", "recommend", "reject"]
    reason: str
    risk: Literal["low", "medium", "high"]
    reputation_delta: int = 0
    notes: list[str] = Field(default_factory=list)


class ExternalProposal(BaseModel):
    agent_id: str
    title: str
    description: str
    payload: dict[str, Any] = Field(default_factory=dict)
