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


class FileSnapshot(BaseModel):
    path: str
    content: str


class CommandResult(BaseModel):
    returncode: int
    stdout: str = ""
    stderr: str = ""
    combined: str = ""
    duration_seconds: float = 0.0
    timed_out: bool = False


class SelfEvolutionAction(BaseModel):
    title: str
    description: str
    risk: Literal["safe", "branch", "recommend"] = "safe"
    patches: list[PatchAction] = Field(default_factory=list)


class ArchitecturePlan(BaseModel):
    title: str
    summary: str
    rationale: str = ""
    route: Literal["branch", "recommend"] = "branch"
    files_touched: list[str] = Field(default_factory=list)
    patch_bundle: list[PatchAction] = Field(default_factory=list)
    proof_requirements: list[str] = Field(default_factory=lambda: [
        "tests pass",
        "no import errors",
        "no policy violations",
    ])
    status: Literal["proposed", "active", "blocked", "complete"] = "proposed"
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class PlannedWorkItem(BaseModel):
    work_id: str
    title: str
    description: str
    mode: Literal["repair", "build", "architecture"] = "build"
    state: Literal["proposed", "active", "blocked", "complete"] = "proposed"
    priority: int = 0
    route: Literal["safe", "branch", "recommend"] = "safe"
    related_files: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class ArchitectureReview(BaseModel):
    diagnosis: str
    system_intent: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    backlog_items: list[str] = Field(default_factory=list)
    self_evolution_actions: list[SelfEvolutionAction] = Field(default_factory=list)
    build_actions: list[PlannedWorkItem] = Field(default_factory=list)
    architecture_plans: list[ArchitecturePlan] = Field(default_factory=list)
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


class SelfEvolutionExecution(BaseModel):
    enabled: bool
    attempted: bool
    applied: bool
    route: str
    summary: str
    reasons: list[str] = Field(default_factory=list)
    proposed_count: int = 0
    applied_count: int = 0
    patches: list[dict[str, Any]] = Field(default_factory=list)


class ExternalProposal(BaseModel):
    agent_id: str
    title: str
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    submitted_at: str = Field(default_factory=utc_now_iso)


class VettingDecision(BaseModel):
    accepted: bool
    route: Literal["safe", "branch", "recommend", "reject"] = "reject"
    reason: str = ""
    risk: Literal["low", "medium", "high"] = "medium"
    reputation_delta: int = 0
    notes: list[str] = Field(default_factory=list)


class AgentReputation(BaseModel):
    agent_id: str
    score: int = 0
    accepted: int = 0
    rejected: int = 0
    impact: Literal["low", "medium", "high"] = "low"
    updated_at: str = Field(default_factory=utc_now_iso)


class FailurePatternRecord(BaseModel):
    signature: str
    success_count: int = 0
    failure_count: int = 0
    last_route: str = ""
    last_summary: str = ""
    related_files: list[str] = Field(default_factory=list)
    updated_at: str = Field(default_factory=utc_now_iso)


class LearningWeights(BaseModel):
    repeated_failure_weight: float = 2.0
    repeated_success_weight: float = 1.5
    stale_advice_decay: float = 0.9
    reviewer_outcome_weight: float = 1.25
    per_file_patch_success_weight: float = 1.5


class PatchProvenance(BaseModel):
    run_id: str
    mode: Literal["repair", "build", "architecture"] = "repair"
    path: str
    description: str = ""
    source: Literal["diagnoser", "reviewer", "planner", "architecture_lane"] = "reviewer"
    route: Literal["safe", "branch", "recommend"] = "safe"
    created_at: str = Field(default_factory=utc_now_iso)


class MetricsLedgerEntry(BaseModel):
    run_id: str
    mode: Literal["repair", "build", "architecture"] = "repair"
    success: bool = False
    review_risk: str = ""
    policy_route: str = ""
    patch_count: int = 0
    self_evolution_count: int = 0
    build_actions_count: int = 0
    architecture_plans_count: int = 0
    created_at: str = Field(default_factory=utc_now_iso)


class RunRecord(BaseModel):
    run_id: str
    command: str
    started_at: str = Field(default_factory=utc_now_iso)
    finished_at: str = ""
    attempt_count: int = 0
    success: bool = False
    summary: str = ""
    selected_mode: Literal["repair", "build", "architecture"] = "repair"
    architecture_review: ArchitectureReview | None = None
    self_evolution: SelfEvolutionExecution | None = None
    diagnostic_history: list[DiagnosticPlan] = Field(default_factory=list)
    patches_applied: list[dict[str, Any]] = Field(default_factory=list)
    rollback_manifest: list[dict[str, Any]] = Field(default_factory=list)
    verification: CommandResult | None = None
    trace: list[dict[str, Any]] = Field(default_factory=list)
    backlog_updates: list[str] = Field(default_factory=list)
    repo_fingerprint: dict[str, Any] = Field(default_factory=dict)


class MemoryState(BaseModel):
    schema_version: str = "3.0"
    architecture_reviews: list[ArchitectureReview] = Field(default_factory=list)
    runs: list[RunRecord] = Field(default_factory=list)
    backlog: list[str] = Field(default_factory=list)
    failure_patterns: dict[str, FailurePatternRecord] = Field(default_factory=dict)
    improvement_history: list[dict[str, Any]] = Field(default_factory=list)
    quarantine_events: list[dict[str, Any]] = Field(default_factory=list)
    reputations: dict[str, AgentReputation] = Field(default_factory=dict)
    metrics_ledger: list[MetricsLedgerEntry] = Field(default_factory=list)
    planned_work: list[PlannedWorkItem] = Field(default_factory=list)
    architecture_queue: list[ArchitecturePlan] = Field(default_factory=list)
    patch_provenance: list[PatchProvenance] = Field(default_factory=list)
    learning_weights: LearningWeights = Field(default_factory=LearningWeights)
    last_saved_at: str = Field(default_factory=utc_now_iso)
