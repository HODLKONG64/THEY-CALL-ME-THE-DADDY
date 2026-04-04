from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from ..models import ArchitectureReview, MemoryState, SelfEvolutionAction


@dataclass
class PlannedSelfEvolution:
    enabled: bool
    actions: list[SelfEvolutionAction] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


class ImprovementPlanner:
    """
    Planner-level pressure control.

    This version does not just look at whether build actions exist.
    It reads recent runtime summaries and uses them to steer:

    - mode selection
    - self-evolution aggressiveness
    - build-vs-repair preference when the repo is green but stalled

    The goal is to stop the system from sitting in a healthy no-op loop
    when build pressure stays active and patch velocity is flat.
    """

    RECENT_SUMMARY_WINDOW = 8
    NO_PATCH_STREAK_THRESHOLD = 3
    LOW_SUCCESS_RATE_THRESHOLD = 0.8
    BUILD_PRESSURE_THRESHOLD = 1
    HIGH_BUILD_PRESSURE_THRESHOLD = 3

    PRESSURE_ESCALATION_MIN_SCORE = 3
    PATCHLESS_ESCALATION_MIN_RUNS = 5
    PATCH_VELOCITY_FLOOR = 0.3
    HIGH_HEALTH_SUCCESS_RATE = 0.85
    MAX_LEVEL2_ACTIONS = 2
    AGGRESSIVE_PRESSURE_SCORE = 5
    AGGRESSIVE_PATCHLESS_RUNS = 4
    AGGRESSIVE_PATCH_VELOCITY_FLOOR = 0.2
    AUTONOMOUS_EXPANSION_PRESSURE_SCORE = 6
    AUTONOMOUS_EXPANSION_PATCHLESS_RUNS = 6
    AUTONOMOUS_EXPANSION_SUCCESS_RATE = 0.85
    SELF_DIRECTED_ARCHITECTURE_PRESSURE_SCORE = 7
    SELF_DIRECTED_ARCHITECTURE_PATCHLESS_RUNS = 7
    SELF_DIRECTED_ARCHITECTURE_SUCCESS_RATE = 0.85

    def merge_review_into_backlog(self, memory: MemoryState, review: ArchitectureReview) -> list[str]:
        additions: list[str] = []

        for item in list(review.recommendations) + list(review.backlog_items):
            if item and item not in memory.backlog:
                memory.backlog.append(item)
                additions.append(item)

        return additions

    def _recent_runs(self, state: Any, limit: int | None = None) -> list[Any]:
        raw_runs = getattr(state, "runs", []) or []
        if not isinstance(raw_runs, list):
            return []

        if limit is None:
            return list(raw_runs)
        return list(raw_runs[-max(1, int(limit)):])

    def _trace_events(self, run: Any) -> list[dict[str, Any]]:
        trace = getattr(run, "trace", None)
        if trace is None and isinstance(run, dict):
            trace = run.get("trace", [])
        if not isinstance(trace, list):
            return []
        return [item for item in trace if isinstance(item, dict)]

    def _summary_event(self, run: Any, event_name: str) -> dict[str, Any] | None:
        for event in self._trace_events(run):
            if event.get("event") == event_name:
                summary = event.get("summary")
                if isinstance(summary, dict):
                    return summary
        return None

    def _latest_summary(self, state: Any, event_name: str) -> dict[str, Any] | None:
        runs = self._recent_runs(state, self.RECENT_SUMMARY_WINDOW)
        for run in reversed(runs):
            summary = self._summary_event(run, event_name)
            if summary:
                return summary
        return None

    def _recent_patch_velocity_summary(self, state: Any) -> dict[str, Any] | None:
        return self._latest_summary(state, "runtime_patch_velocity_summary")

    def _recent_run_health_summary(self, state: Any) -> dict[str, Any] | None:
        return self._latest_summary(state, "runtime_run_health_summary")

    def _recent_build_action_summary(self, state: Any) -> dict[str, Any] | None:
        return self._latest_summary(state, "runtime_build_action_summary")

    def _recent_build_pressure_summary(self, state: Any) -> dict[str, Any] | None:
        return self._latest_summary(state, "runtime_build_pressure_summary")

    def _recent_no_patch_streak(self, state: Any) -> int:
        streak = 0
        for run in reversed(self._recent_runs(state, self.RECENT_SUMMARY_WINDOW)):
            if isinstance(run, dict):
                patch_count = int(run.get("patch_count", 0) or 0)
            else:
                patch_count = int(getattr(run, "patch_count", 0) or 0)

            if patch_count > 0:
                break
            streak += 1
        return streak

    def _build_pressure_score(self, state: Any) -> int:
        summary = self._recent_build_pressure_summary(state)
        if summary:
            return int(summary.get("pressure_score", 0) or 0)

        fallback = self._recent_build_action_summary(state)
        if fallback:
            return int(fallback.get("count", 0) or 0)

        return 0

    def _build_pressure_source(self, state: Any) -> str:
        summary = self._recent_build_pressure_summary(state)
        if summary:
            return "runtime_build_pressure_summary"

        fallback = self._recent_build_action_summary(state)
        if fallback:
            return "runtime_build_action_summary"

        return "none"

    def _build_pressure_active(self, state: Any) -> bool:
        summary = self._recent_build_pressure_summary(state)
        if summary:
            return bool(summary.get("active", False)) and self._build_pressure_score(state) >= self.BUILD_PRESSURE_THRESHOLD

        fallback = self._recent_build_action_summary(state)
        if fallback:
            return int(fallback.get("count", 0) or 0) > 0

        return False

    def _high_build_pressure(self, state: Any) -> bool:
        return self._build_pressure_score(state) >= self.HIGH_BUILD_PRESSURE_THRESHOLD

    def _average_patch_count(self, state: Any) -> float:
        summary = self._recent_patch_velocity_summary(state)
        if not summary:
            return 0.0
        return float(summary.get("average_patch_count", 0) or 0)

    def summarize_pressure_escalation_decision(self, state: Any) -> dict[str, Any]:
        build_pressure_score = self._build_pressure_score(state)
        no_patch_streak = self._recent_no_patch_streak(state)
        average_patch_count = self._average_patch_count(state)

        run_health = self._recent_run_health_summary(state)
        success_rate = float(run_health.get("success_rate", 0) or 0) if run_health else 0.0
        build_pressure_source = self._build_pressure_source(state)
        build_pressure_active = self._build_pressure_active(state)

        aggressive_mode = (
            build_pressure_score >= self.AGGRESSIVE_PRESSURE_SCORE
            and no_patch_streak >= self.AGGRESSIVE_PATCHLESS_RUNS
            and average_patch_count <= self.AGGRESSIVE_PATCH_VELOCITY_FLOOR
            and success_rate >= self.HIGH_HEALTH_SUCCESS_RATE
        )

        force_deeper_action = (
            build_pressure_score >= self.PRESSURE_ESCALATION_MIN_SCORE
            and no_patch_streak >= self.PATCHLESS_ESCALATION_MIN_RUNS
            and average_patch_count < self.PATCH_VELOCITY_FLOOR
            and success_rate >= self.HIGH_HEALTH_SUCCESS_RATE
        ) or aggressive_mode

        return {
            "build_pressure_score": build_pressure_score,
            "build_pressure_source": build_pressure_source,
            "build_pressure_active": build_pressure_active,
            "no_patch_streak": no_patch_streak,
            "average_patch_count": average_patch_count,
            "success_rate": success_rate,
            "aggressive_mode": aggressive_mode,
            "force_deeper_action": force_deeper_action,
        }





    def summarize_self_directed_architecture_decision(self, state: Any) -> dict[str, Any]:
        pressure = self.summarize_pressure_escalation_decision(state)
        pressure_score = int(pressure.get("build_pressure_score", 0) or 0)
        no_patch_streak = int(pressure.get("no_patch_streak", 0) or 0)
        average_patch_count = float(pressure.get("average_patch_count", 0) or 0)
        success_rate = float(pressure.get("success_rate", 0) or 0)

        self_directed_architecture = (
            pressure_score >= self.SELF_DIRECTED_ARCHITECTURE_PRESSURE_SCORE
            and no_patch_streak >= self.SELF_DIRECTED_ARCHITECTURE_PATCHLESS_RUNS
            and average_patch_count <= self.AGGRESSIVE_PATCH_VELOCITY_FLOOR
            and success_rate >= self.SELF_DIRECTED_ARCHITECTURE_SUCCESS_RATE
        )

        return {
            "pressure_score": pressure_score,
            "no_patch_streak": no_patch_streak,
            "average_patch_count": average_patch_count,
            "success_rate": success_rate,
            "self_directed_architecture": self_directed_architecture,
        }

    def summarize_autonomous_expansion_decision(self, state: Any) -> dict[str, Any]:
        pressure = self.summarize_pressure_escalation_decision(state)
        pressure_score = int(pressure.get("build_pressure_score", 0) or 0)
        no_patch_streak = int(pressure.get("no_patch_streak", 0) or 0)
        average_patch_count = float(pressure.get("average_patch_count", 0) or 0)
        success_rate = float(pressure.get("success_rate", 0) or 0)

        autonomous_expansion = (
            pressure_score >= self.AUTONOMOUS_EXPANSION_PRESSURE_SCORE
            and no_patch_streak >= self.AUTONOMOUS_EXPANSION_PATCHLESS_RUNS
            and average_patch_count <= self.AGGRESSIVE_PATCH_VELOCITY_FLOOR
            and success_rate >= self.AUTONOMOUS_EXPANSION_SUCCESS_RATE
        )

        return {
            "pressure_score": pressure_score,
            "no_patch_streak": no_patch_streak,
            "average_patch_count": average_patch_count,
            "success_rate": success_rate,
            "autonomous_expansion": autonomous_expansion,
        }

    def _should_force_build_from_pressure(self, state: Any) -> bool:
        decision = self.summarize_pressure_escalation_decision(state)
        return bool(decision.get("force_deeper_action", False))

    def plan_self_evolution(
        self,
        review: ArchitectureReview,
        enabled: bool,
        max_actions: int,
        memory: Any | None = None,
    ) -> PlannedSelfEvolution:
        if not enabled:
            return PlannedSelfEvolution(
                enabled=False,
                actions=[],
                reasons=["Self-evolution disabled"],
            )

        raw_actions = getattr(review, "self_evolution_actions", []) or []
        if not isinstance(raw_actions, list):
            raw_actions = []

        safe_actions = [
            action
            for action in raw_actions
            if getattr(action, "risk", "") == "safe" and bool(getattr(action, "patches", []))
        ]

        if not safe_actions:
            return PlannedSelfEvolution(
                enabled=True,
                actions=[],
                reasons=["No valid safe actions found"],
            )

        effective_max = max(1, int(max_actions))
        reasons: list[str] = []

        if memory is not None:
            state: Any = memory.state if hasattr(memory, "state") else memory
            patch_velocity = self._recent_patch_velocity_summary(state)
            run_health = self._recent_run_health_summary(state)
            build_pressure = self._recent_build_pressure_summary(state)
            build_pressure_score = self._build_pressure_score(state)
            no_patch_streak = self._recent_no_patch_streak(state)

            if patch_velocity:
                runs_with_patches = int(patch_velocity.get("runs_with_patches", 0) or 0)
                window = int(patch_velocity.get("window", 0) or 0)
                if runs_with_patches == 0 and window > 0:
                    effective_max = min(effective_max, 1)
                    reasons.append(
                        f"Recent patch velocity is flat across the last {window} runs; limiting self-evolution to 1 action."
                    )

            if run_health:
                success_rate = float(run_health.get("success_rate", 0) or 0)
                sample_size = int(run_health.get("sample_size", 0) or 0)
                if sample_size > 0 and success_rate < self.LOW_SUCCESS_RATE_THRESHOLD:
                    effective_max = min(effective_max, 1)
                    reasons.append(
                        f"Recent run health success_rate={success_rate} across sample_size={sample_size}; keeping self-evolution conservative."
                    )

            if build_pressure and bool(build_pressure.get("active", False)):
                reasons.append(
                    f"Build pressure remains active with pressure_score={build_pressure_score}."
                )

            if self._build_pressure_active(state) and no_patch_streak >= self.NO_PATCH_STREAK_THRESHOLD:
                effective_max = max(1, min(effective_max, 1))
                reasons.append(
                    f"No-patch streak={no_patch_streak} with active build pressure; preserving one bounded self-evolution action."
                )

            if self._high_build_pressure(state):
                success_rate = float(run_health.get("success_rate", 1.0) or 1.0) if run_health else 1.0
                if success_rate >= 0.95:
                    effective_max = max(effective_max, min(2, len(safe_actions), max_actions))
                    reasons.append(
                        f"High build pressure detected (pressure_score={build_pressure_score}) with strong health; allowing up to {effective_max} safe actions."
                    )

            if self._should_force_build_from_pressure(state):
                effective_max = max(1, min(self.MAX_LEVEL2_ACTIONS, len(safe_actions), max_actions))
                decision = self.summarize_pressure_escalation_decision(state)
                reasons.append(
                    "Level 3 escalation engaged: strong pressure with healthy but under-producing patch velocity justifies deeper bounded action."
                )
                autonomous = self.summarize_autonomous_expansion_decision(state)
                if autonomous.get('autonomous_expansion', False):
                    reasons.append(
                        "Level 4 autonomous expansion is armed: sustained pressure and prolonged patch drought now justify forced bounded expansion work."
                    )
                    architecture_decision = self.summarize_self_directed_architecture_decision(state)
                    if architecture_decision.get("self_directed_architecture", False):
                        reasons.append(
                            "Level 5 self-directed architecture is armed: sustained pressure now justifies planner-led architecture work instead of helper fallback."
                        )
                reasons.append(
                    f"Escalation metrics: pressure_score={decision['build_pressure_score']}, "
                    f"pressure_source={decision['build_pressure_source']}, "
                    f"no_patch_streak={decision['no_patch_streak']}, "
                    f"average_patch_count={decision['average_patch_count']}, "
                    f"success_rate={decision['success_rate']}, "
                    f"aggressive_mode={decision['aggressive_mode']}."
                )

        if effective_max <= 0:
            return PlannedSelfEvolution(
                enabled=True,
                actions=[],
                reasons=reasons + [f"Capped self-evolution actions from {len(safe_actions)} to 0."],
            )

        if len(safe_actions) > effective_max:
            reasons.append(f"Capped self-evolution actions from {len(safe_actions)} to {effective_max}.")
            safe_actions = safe_actions[:effective_max]

        return PlannedSelfEvolution(
            enabled=True,
            actions=safe_actions,
            reasons=reasons,
        )

    def select_build_work(self, planned_work: Iterable[Any]) -> object | None:
        try:
            candidates = [
                item for item in planned_work
                if getattr(item, "state", "") in {"proposed", "active"}
            ]
        except TypeError:
            return None

        if not candidates:
            return None

        candidates.sort(
            key=lambda item: (
                getattr(item, "priority", 0),
                getattr(item, "created_at", "")
            )
        )
        return candidates[0]

    def should_trigger_architecture(self, memory: Any) -> bool:
        failure_patterns = getattr(memory, "failure_patterns", {})
        if not hasattr(failure_patterns, "values"):
            return False

        ranked = sorted(
            failure_patterns.values(),
            key=lambda item: (getattr(item, "failure_count", 0), getattr(item, "updated_at", "")),
            reverse=True,
        )
        if not ranked:
            return False

        return int(getattr(ranked[0], "failure_count", 0) or 0) >= 3

    def decide_mode(self, memory, review: ArchitectureReview) -> str:
        state: Any = memory.state if hasattr(memory, "state") else memory

        architecture_plans = getattr(review, "architecture_plans", None)
        if isinstance(architecture_plans, list) and architecture_plans:
            if self.should_trigger_architecture(state):
                return "architecture"

        self_evolution_actions = getattr(review, "self_evolution_actions", None)
        if isinstance(self_evolution_actions, list) and self_evolution_actions:
            return "build"
        elif self_evolution_actions:
            return "repair"

        patch_velocity = self._recent_patch_velocity_summary(state)
        run_health = self._recent_run_health_summary(state)
        no_patch_streak = self._recent_no_patch_streak(state)
        build_pressure_active = self._build_pressure_active(state)
        build_pressure_score = self._build_pressure_score(state)

        if run_health:
            success_rate = float(run_health.get("success_rate", 0) or 0)
            sample_size = int(run_health.get("sample_size", 0) or 0)
            if sample_size > 0 and success_rate < self.LOW_SUCCESS_RATE_THRESHOLD:
                return "repair"

        if self._should_force_build_from_pressure(state):
            return "build"

        if patch_velocity:
            runs_with_patches = int(patch_velocity.get("runs_with_patches", 0) or 0)
            sample_size = int(patch_velocity.get("sample_size", 0) or 0)

            if sample_size > 0 and runs_with_patches == 0:
                if build_pressure_active or no_patch_streak >= self.NO_PATCH_STREAK_THRESHOLD:
                    return "build"

        if build_pressure_active and build_pressure_score >= self.BUILD_PRESSURE_THRESHOLD:
            return "build"

        planned_work = getattr(state, "planned_work", None)
        if isinstance(planned_work, list):
            if planned_work:
                return "build"
        elif isinstance(planned_work, str):
            return "build"

        return "repair"
