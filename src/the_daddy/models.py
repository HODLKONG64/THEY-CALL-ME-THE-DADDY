from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


DEFAULT_TRUST_SCORE = 50


def _to_mapping_like(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None

    if isinstance(value, dict):
        return dict(value)

    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump(mode="json")
            if isinstance(dumped, dict):
                return dict(dumped)
        except Exception:
            pass

    if hasattr(value, "__dict__"):
        try:
            return dict(vars(value))
        except Exception:
            return None

    return None


class PatchAction(BaseModel):
    path: str
    operation: Literal["replace_file", "regex_replace"]
    new_content: str | None = None
    pattern: str | None = None
    replacement: str | None = None
    description: str = ""

    @model_validator(mode="after")
    def _validate_operation_payload(self) -> PatchAction:
        if self.operation == "replace_file":
            if not self.new_content:
                raise ValueError("replace_file requires new_content")
        elif self.operation == "regex_replace":
            if not self.pattern:
                raise ValueError("regex_replace requires pattern")
            if not self.replacement:
                raise ValueError("regex_replace requires replacement")
        return self


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

    @field_validator("self_evolution_actions", mode="before")
    @classmethod
    def _normalize_self_evolution_actions(cls, value: Any) -> list[Any]:
        if value is None:
            return []

        if not isinstance(value, list):
            value = [value]

        normalized: list[dict[str, Any]] = []

        for raw_action in value:
            action_map = _to_mapping_like(raw_action)
            if not action_map:
                continue

            patches_raw = action_map.get("patches", [])
            if patches_raw is None:
                patches_raw = []

            if not isinstance(patches_raw, list):
                patches_raw = [patches_raw]

            valid_patches: list[PatchAction] = []
            for raw_patch in patches_raw:
                patch_map = _to_mapping_like(raw_patch)
                if not patch_map:
                    continue
                try:
                    valid_patches.append(PatchAction.model_validate(patch_map))
                except Exception:
                    continue

            # If caller supplied patches but none were valid, drop the whole action.
            # This lets malformed entries exist in input without forcing build mode later.
            if patches_raw and not valid_patches:
                continue

            normalized.append(
                {
                    "title": str(action_map.get("title", "")),
                    "description": str(action_map.get("description", "")),
                    "risk": action_map.get("risk", "safe"),
                    "patches": [patch.model_dump(mode="json") for patch in valid_patches],
                }
            )

        return normalized


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

    @field_validator("route", mode="before")
    @classmethod
    def _normalize_legacy_route(cls, value: Any) -> Any:
        return "safe" if value == "accept" else value


class AgentReputation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    agent_id: str = Field(validation_alias=AliasChoices("agent_id", "agent_name"))
    trust_score: int = Field(default=DEFAULT_TRUST_SCORE, validation_alias=AliasChoices("trust_score", "score"))
    accepted_count: int = Field(default=0, validation_alias=AliasChoices("accepted_count", "accepted"))
    staged_count: int = Field(default=0, validation_alias=AliasChoices("staged_count", "staged"))
    rejected_count: int = Field(default=0, validation_alias=AliasChoices("rejected_count", "rejected"))
    impact: Literal["low", "medium", "high"] = "low"
    updated_at: str = Field(default_factory=utc_now_iso)


Reputation = AgentReputation
VetDecision = VettingDecision


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


# === LEGACY COMPAT (FINAL LOCK) ===
FailurePattern = FailurePatternRecord


class PatchResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    path: str = ""
    description: str = ""
    success: bool = True


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="allow")

    route: str = "safe"
    reason: str = ""
    allowed: bool = True
