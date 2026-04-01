from __future__ import annotations

from datetime import datetime, timezone

from .agents.diagnoser import Diagnoser
from .agents.improvement_planner import ImprovementPlanner
from .agents.reviewer import WakeReviewer
from .agents.vetter import ExternalVetter
from .config import Settings, get_settings
from .logging_utils import write_local_summary
from .memory.r2_store import R2Store
from .memory.repository import MemoryRepository
from .models import ArchitectureReview, ExternalProposal, RunRecord, utc_now_iso
from .policy import classify_patch_risk
from .runtime.command_runner import run_command
from .runtime.file_tools import apply_patch_action, find_referenced_files, gather_file_context
from .telemetry import TraceBuffer


def make_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class DaddyEngine:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.store = R2Store(self.settings)
        self.memory = MemoryRepository(self.store)
        self.reviewer = WakeReviewer(self.settings) if self.settings.has_openai else None
        self.diagnoser = Diagnoser(self.settings) if self.settings.has_openai else None
        self.vetter = ExternalVetter(self.settings) if self.settings.has_openai else None
        self.improvement_planner = ImprovementPlanner()

    def architecture_review(self, trace: TraceBuffer) -> ArchitectureReview | None:
        if not self.reviewer:
            return None
        trace.add("architecture_review.start")
        latest = self.memory.latest_review()
        review = self.reviewer.review(
            memory_snapshot=self.memory.state.model_dump(mode="json"),
            repo_root=self.settings.target_root,
            recent_summary=latest.diagnosis if latest else "",
        )
        self.memory.add_architecture_review(review)
        trace.add(
            "architecture_review.done",
            risk=review.risk_level,
            recommendations=len(review.recommendations),
            self_evolution_actions=len(review.self_evolution_actions),
        )
        return review

    def _execute_self_evolution(self, review: ArchitectureReview, trace: TraceBuffer):
        planned = self.improvement_planner.plan_self_evolution(
            review,
            enabled=self.settings.enable_self_evolution,
            max_actions=self.settings.self_evolution_max_actions,
        )
        proposed_count = len(planned.actions)
        if not planned.actions:
            return self.improvement_planner.build_execution_result(
                enabled=self.settings.enable_self_evolution,
                attempted=False,
                applied=False,
                route="disabled" if not self.settings.enable_self_evolution else "none",
                summary=planned.reasons[0] if planned.reasons else "No self-evolution action planned.",
                reasons=planned.reasons,
                proposed_count=0,
                applied_count=0,
                patches=[],
            )

        trace.add("self_evolution.planned", proposed_count=proposed_count)
        policy = classify_patch_risk(planned.actions)
        trace.add("self_evolution.policy", route=policy.route, passed=policy.passed)

        if not policy.passed or policy.route != "safe":
            reasons = [*planned.reasons, *policy.reasons]
            self.memory.record_improvement_result(
                "Wake review self-evolution",
                applied=False,
                payload={"route": policy.route, "reasons": reasons, "proposed_count": proposed_count},
            )
            return self.improvement_planner.build_execution_result(
                enabled=self.settings.enable_self_evolution,
                attempted=True,
                applied=False,
                route=policy.route,
                summary="Self-evolution changes were generated but not auto-applied.",
                reasons=reasons,
                proposed_count=proposed_count,
                applied_count=0,
                patches=[],
            )

        patches = []
        for change in planned.actions:
            patches.append(apply_patch_action(self.settings.target_root, change, self.settings.allow_extensions))
        reasons = [*planned.reasons, *policy.reasons]
        self.memory.record_improvement_result(
            "Wake review self-evolution",
            applied=True,
            payload={"route": policy.route, "reasons": reasons, "proposed_count": proposed_count, "patches": patches},
        )
        trace.add("self_evolution.applied", applied_count=len(patches))
        return self.improvement_planner.build_execution_result(
            enabled=self.settings.enable_self_evolution,
            attempted=True,
            applied=True,
            route=policy.route,
            summary="Applied safe self-evolution changes from wake audit.",
            reasons=reasons,
            proposed_count=proposed_count,
            applied_count=len(patches),
            patches=patches,
        )

    def run(self) -> RunRecord:
        run_id = make_run_id()
        trace = TraceBuffer()
        record = RunRecord(run_id=run_id, command=self.settings.command)
        trace.add("run.start", run_id=run_id, command=self.settings.command)

        review = self.architecture_review(trace)
        record.architecture_review = review
        if review:
            record.backlog_updates = self.improvement_planner.merge_review_into_backlog(self.memory.state, review)
            record.self_evolution = self._execute_self_evolution(review, trace)
            self.memory.save()

        prior_attempts = []
        last_result = None

        for attempt in range(1, self.settings.max_attempts + 1):
            trace.add("attempt.start", attempt=attempt)
            result = run_command(
                self.settings.command,
                cwd=self.settings.target_root,
                timeout_seconds=self.settings.run_timeout_seconds,
            )
            last_result = result
            record.attempt_count = attempt
            if result.returncode == 0:
                record.success = True
                record.summary = f"Command succeeded on attempt {attempt}."
                trace.add("attempt.success", attempt=attempt)
                break

            if not self.diagnoser:
                record.summary = "Command failed and OpenAI is not configured, so no diagnosis was produced."
                trace.add("attempt.fail.no_openai", attempt=attempt)
                break

            referenced = find_referenced_files(result.combined, self.settings.target_root, self.settings.allow_extensions)
            file_context = gather_file_context(
                self.settings.target_root,
                referenced,
                max_files=8,
                max_bytes=self.settings.max_file_bytes,
            )
            plan = self.diagnoser.diagnose(
                command=self.settings.command,
                output=result.combined,
                files=[f.model_dump(mode="json") for f in file_context],
                prior_attempts=prior_attempts,
            )
            record.diagnostic_history.append(plan)
            trace.add("diagnosis.generated", attempt=attempt, confidence=plan.confidence, change_count=len(plan.changes))

            policy = classify_patch_risk(plan.changes)
            trace.add("diagnosis.policy", attempt=attempt, route=policy.route, passed=policy.passed)

            signature = self.memory.fingerprint(plan.root_cause + result.stderr[:2000])

            if not policy.passed or policy.route == "recommend" or not self.settings.enable_patching:
                self.memory.record_failure_pattern(
                    signature,
                    {"attempt": attempt, "diagnosis": plan.diagnosis, "route": policy.route, "reasons": policy.reasons},
                    success=False,
                )
                record.summary = f"Patch blocked or recommend-only on attempt {attempt}: {'; '.join(policy.reasons)}"
                prior_attempts.append({"attempt": attempt, "blocked": True, "reasons": policy.reasons})
                break

            try:
                patch_events = []
                for change in plan.changes:
                    patch_events.append(apply_patch_action(self.settings.target_root, change, self.settings.allow_extensions))
                record.patches_applied.extend(patch_events)
                self.memory.record_failure_pattern(
                    signature,
                    {"attempt": attempt, "diagnosis": plan.diagnosis, "patches": patch_events},
                    success=True,
                )
                prior_attempts.append({"attempt": attempt, "applied": True, "diffs": patch_events})
                trace.add("patches.applied", attempt=attempt, count=len(patch_events))
            except Exception as exc:
                record.summary = f"Patch application failed: {exc}"
                trace.add("patches.failed", attempt=attempt, error=str(exc))
                break

        if last_result is not None:
            record.verification = last_result
        if not record.summary:
            record.summary = "Run finished." if record.success else "Run finished without a successful repair."
        record.finished_at = utc_now_iso()
        record.trace = trace.export()

        self.memory.add_run(record)
        write_local_summary(record.summary, self.settings.local_state_dir)
        return record

    def vet_external_proposal(self, proposal: ExternalProposal) -> dict:
        event = proposal.model_dump(mode="json")
        if not self.vetter:
            decision = {
                "accepted": False,
                "route": "reject",
                "reason": "OpenAI not configured.",
                "risk": "high",
                "reputation_delta": -5,
                "notes": ["Set OPENAI_API_KEY to enable vetting."],
            }
        else:
            decision_obj = self.vetter.vet(proposal, self.memory.state.model_dump(mode="json"))
            rep = self.memory.update_reputation(proposal.agent_id, decision_obj)
            decision = decision_obj.model_dump(mode="json")
            decision["reputation"] = rep.model_dump(mode="json")
        event["decision"] = decision
        self.memory.add_quarantine_event(event)
        return event
