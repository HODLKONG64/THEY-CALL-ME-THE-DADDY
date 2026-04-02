from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..config import Settings
from ..models import (
    ArchitecturePlan,
    ArchitectureReview,
    PatchAction,
    PlannedWorkItem,
    SelfEvolutionAction,
)
from .openai_client import OpenAIJSONClient


BANNED_TEST_PATH_PATTERNS = {
    "tests/test_wake_review_invariant.py",
    "tests/test_wake_review_invariants.py",
    "tests/test_wake_review_output.py",
    "tests/test_wake_review_contract.py",
    "tests/test_self_evolution.py",
}

BANNED_TEST_TITLE_PATTERNS = (
    "wake-review invariant",
    "wake review invariant",
    "wake-review output",
    "wake review output",
    "wake-review contract",
    "wake review contract",
    "self-evolution action existence",
    "self evolution action existence",
    "safe self-evolution action existence",
)

PROACTIVE_RUNTIME_PATH = "src/the_daddy/runtime/trace_summary.py"
FALLBACK_RUNTIME_PATH = "src/the_daddy/runtime/reviewer_fallback.py"
ARCHITECTURE_RUNTIME_PATH = "src/the_daddy/runtime/architecture_probe.py"
BANNED_SELF_EVOLUTION_PATHS = {
    "src/the_daddy/runtime/command_runner.py",
}

SAFE_NEW_FILE_ALLOWLIST = {
    PROACTIVE_RUNTIME_PATH,
    FALLBACK_RUNTIME_PATH,
    ARCHITECTURE_RUNTIME_PATH,
}


class WakeReviewer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAIJSONClient(settings) if settings.has_openai else None

    def _repo_snapshot(self, repo_root: Path) -> dict[str, Any]:
        tracked: list[str] = []
        preview_files: list[dict[str, str]] = []
        ignored_parts = {".git", ".venv", "venv", "__pycache__", "doctor_local", ".pytest_cache", "build", "dist"}

        for path in sorted(repo_root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in ignored_parts for part in path.parts):
                continue

            rel = str(path.relative_to(repo_root))
            tracked.append(rel)

            if len(preview_files) < 40 and path.suffix in {".py", ".md", ".yml", ".yaml", ".toml", ".json"}:
                try:
                    preview_files.append(
                        {
                            "path": rel,
                            "content_preview": path.read_text(encoding="utf-8", errors="ignore")[:6000],
                        }
                    )
                except Exception:
                    continue

            if len(tracked) >= 250:
                break

        return {"tracked_files": tracked, "preview_files": preview_files}

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    def _normalize_path(self, path: str) -> str:
        cleaned = str(path or "").strip().replace("\\", "/")
        while "//" in cleaned:
            cleaned = cleaned.replace("//", "/")
        if cleaned.startswith("./"):
            cleaned = cleaned[2:]
        return cleaned

    def _normalize_phrase(self, text: str) -> str:
        cleaned = re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()
        return re.sub(r"\s+", " ", cleaned)

    def _semantic_tokens(self, text: str) -> set[str]:
        normalized = self._normalize_phrase(text)
        parts = normalized.split()

        canonical_map = {
            "wake": "wake_review",
            "review": "wake_review",
            "output": "review_contract",
            "outputs": "review_contract",
            "contract": "review_contract",
            "contracts": "review_contract",
            "invariant": "review_contract",
            "invariants": "review_contract",
            "safe": "safety_rule",
            "safely": "safety_rule",
            "safety": "safety_rule",
            "self": "self_evolution",
            "evolution": "self_evolution",
            "action": "action_requirement",
            "actions": "action_requirement",
            "exists": "existence_check",
            "exist": "existence_check",
            "existence": "existence_check",
            "ensure": "existence_check",
            "ensures": "existence_check",
            "ensuring": "existence_check",
            "require": "action_requirement",
            "requires": "action_requirement",
            "requirement": "action_requirement",
            "requirements": "action_requirement",
            "test": "test",
            "tests": "test",
            "regression": "regression_test",
            "rollback": "rollback",
            "rollback_metadata": "rollback",
            "rollbackmanifest": "rollback",
            "manifest": "rollback",
            "metadata": "metadata",
            "observability": "observability",
            "visibility": "observability",
            "alignment": "alignment",
            "schema": "schema",
            "protected": "protected_file",
            "guard": "guard",
            "guards": "guard",
            "filetools": "file_tools",
            "core": "protected_file",
            "trace": "trace",
            "logging": "observability",
            "runtime": "runtime",
            "telemetry": "observability",
        }

        stopwords = {
            "add",
            "create",
            "introduce",
            "implement",
            "improve",
            "expand",
            "cover",
            "covers",
            "covering",
            "for",
            "the",
            "a",
            "an",
            "to",
            "of",
            "and",
            "that",
            "with",
            "within",
            "all",
            "current",
            "provided",
            "based",
            "ensure",
            "ensures",
            "ensuring",
        }

        tokens: set[str] = set()
        for part in parts:
            if not part or part in stopwords:
                continue
            tokens.add(canonical_map.get(part, part))

        if "wake_review" in tokens and "review_contract" in tokens:
            tokens.add("wake_review_contract_test")
        if "test" in tokens and "self_evolution" in tokens and "action_requirement" in tokens:
            tokens.add("self_evolution_action_test")
        if "test" in tokens and "existence_check" in tokens:
            tokens.add("existence_test")
        if "trace" in tokens and "observability" in tokens:
            tokens.add("trace_observability")
        if "runtime" in tokens and "observability" in tokens:
            tokens.add("runtime_observability")

        return tokens

    def _backlog_items_semantically_similar(self, left: str, right: str) -> bool:
        left_tokens = self._semantic_tokens(left)
        right_tokens = self._semantic_tokens(right)

        if not left_tokens or not right_tokens:
            return False

        overlap = left_tokens & right_tokens

        if "wake_review_contract_test" in overlap:
            return True

        if "self_evolution_action_test" in overlap and "test" in overlap:
            return True

        if {"test", "wake_review", "review_contract"} <= overlap:
            return True

        if {"test", "self_evolution", "action_requirement"} <= overlap:
            return True

        if {"rollback", "observability"} <= overlap:
            return True

        if "trace_observability" in overlap:
            return True

        similarity = len(overlap) / max(1, min(len(left_tokens), len(right_tokens)))
        return similarity >= 0.75

    def _tokenize_test_stem(self, path: str) -> set[str]:
        stem = Path(path).stem.lower()
        parts = re.split(r"[^a-z0-9]+", stem)
        stopwords = {
            "test",
            "tests",
            "wake",
            "review",
            "output",
            "outputs",
            "contract",
            "contracts",
            "safe",
            "action",
            "actions",
            "build",
            "plan",
            "plans",
            "invariant",
            "invariants",
            "regression",
        }
        return {part for part in parts if part and part not in stopwords}

    def _existing_backlog_items(self, memory_snapshot: dict[str, Any]) -> list[str]:
        items: list[str] = []

        for item in memory_snapshot.get("backlog", []) or []:
            text = str(item).strip()
            if text:
                items.append(text)

        reviews = memory_snapshot.get("architecture_reviews", []) or []
        for review in reviews[-6:]:
            if not isinstance(review, dict):
                continue
            for item in review.get("backlog_items", []) or []:
                text = str(item).strip()
                if text:
                    items.append(text)

        return items

    def _filter_repetitive_backlog_items(
        self,
        items: list[str],
        memory_snapshot: dict[str, Any],
    ) -> tuple[list[str], list[str]]:
        existing_items = self._existing_backlog_items(memory_snapshot)
        kept: list[str] = []
        removed: list[str] = []

        for item in items:
            text = str(item).strip()
            if not text:
                continue

            duplicate = False

            for prior in existing_items:
                if self._backlog_items_semantically_similar(text, prior):
                    duplicate = True
                    break

            if not duplicate:
                for prior in kept:
                    if self._backlog_items_semantically_similar(text, prior):
                        duplicate = True
                        break

            if duplicate:
                removed.append(text)
            else:
                kept.append(text)

        return kept, removed

    def _is_test_only_action(self, action: SelfEvolutionAction) -> bool:
        if not action.patches:
            return False
        return all((self._normalize_path(patch.path or "")).startswith("tests/") for patch in action.patches)

    def _is_banned_test_path(self, path: str) -> bool:
        normalized = self._normalize_path(path).lower()
        return normalized in BANNED_TEST_PATH_PATTERNS

    def _has_banned_test_title(self, text: str) -> bool:
        normalized = self._normalize_phrase(text)
        return any(pattern in normalized for pattern in BANNED_TEST_TITLE_PATTERNS)

    def _is_banned_test_action(self, action: SelfEvolutionAction) -> bool:
        if self._has_banned_test_title(getattr(action, "title", "")):
            return True
        if self._has_banned_test_title(getattr(action, "description", "")):
            return True

        for patch in action.patches or []:
            if self._is_banned_test_path(getattr(patch, "path", "")):
                return True

        return False

    def _is_repetitive_test_action(self, action: SelfEvolutionAction, tracked_files: list[str]) -> bool:
        if not self._is_test_only_action(action):
            return False

        tracked_tests = [path for path in tracked_files if path.startswith("tests/")]

        for patch in action.patches:
            target = self._normalize_path(patch.path or "")
            if target in tracked_tests:
                return True

            target_tokens = self._tokenize_test_stem(target)
            if not target_tokens:
                continue

            for existing in tracked_tests:
                existing_tokens = self._tokenize_test_stem(existing)
                if not existing_tokens:
                    continue

                overlap = len(target_tokens & existing_tokens)
                smallest = min(len(target_tokens), len(existing_tokens))
                if smallest > 0 and overlap >= smallest:
                    return True

        return False

    def _is_allowed_patch_path(self, path: str, tracked_files: list[str]) -> bool:
        normalized = self._normalize_path(path)

        if not normalized:
            return False

        if normalized in BANNED_SELF_EVOLUTION_PATHS:
            return False

        if normalized in tracked_files:
            return True

        if normalized in SAFE_NEW_FILE_ALLOWLIST:
            return True

        return False

    def _filter_low_value_actions(
        self,
        actions: list[SelfEvolutionAction],
        tracked_files: list[str],
    ) -> tuple[list[SelfEvolutionAction], list[str]]:
        kept: list[SelfEvolutionAction] = []
        removed_notes: list[str] = []

        for action in actions:
            if self._is_banned_test_action(action):
                removed_notes.append(
                    f"Blocked permanently banned test-loop action: {action.title}"
                )
                continue

            if self._is_repetitive_test_action(action, tracked_files):
                removed_notes.append(
                    f"Suppressed repetitive test-only self-evolution action: {action.title}"
                )
                continue

            invalid_paths: list[str] = []
            for patch in action.patches or []:
                patch_path = self._normalize_path(getattr(patch, "path", ""))
                if not self._is_allowed_patch_path(patch_path, tracked_files):
                    invalid_paths.append(patch_path)

            if invalid_paths:
                removed_notes.append(
                    f"Blocked self-evolution action with non-tracked, banned, or non-allowlisted paths: {action.title} -> {', '.join(invalid_paths)}"
                )
                continue

            kept.append(action)

        return kept, removed_notes

    def _fallback_patch_action(self, repo_root: Path) -> SelfEvolutionAction | None:
        target = repo_root / "src" / "the_daddy" / "runtime" / "reviewer_fallback.py"
        if target.exists():
            return None

        new_content = '''from __future__ import annotations

from typing import Any


def fallback_review_summary(reason: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(details or {})
    payload["reason"] = reason
    payload["source"] = "wake_reviewer_fallback"
    return payload
'''
        return SelfEvolutionAction(
            title="Add safe reviewer fallback helper",
            description="Create a non-protected runtime helper so fallback review output still produces an executable bounded patch.",
            risk="safe",
            patches=[
                PatchAction(
                    path=FALLBACK_RUNTIME_PATH,
                    operation="replace_file",
                    new_content=new_content,
                    description="Add runtime reviewer fallback helper.",
                )
            ],
        )

    def _proactive_runtime_action(self, repo_root: Path) -> SelfEvolutionAction | None:
        target = repo_root / PROACTIVE_RUNTIME_PATH
        if target.exists():
            return None

        new_content = '''from __future__ import annotations

from collections import Counter
from typing import Any


def summarize_trace(trace: list[dict[str, Any]] | None) -> dict[str, Any]:
    items = trace or []
    counts = Counter()

    for item in items:
        event = str(item.get("event", "unknown")).strip() or "unknown"
        counts[event] += 1

    return {
        "total_events": len(items),
        "event_counts": dict(counts),
        "last_event": items[-1] if items else None,
    }
'''
        return SelfEvolutionAction(
            title="Add runtime trace summarizer utility",
            description="Proactively add a bounded runtime observability helper so future runs can reason about trace event distributions without test farming.",
            risk="safe",
            patches=[
                PatchAction(
                    path=PROACTIVE_RUNTIME_PATH,
                    operation="replace_file",
                    new_content=new_content,
                    description="Add runtime trace summarizer utility for observability.",
                )
            ],
        )

    def _default_build_action(self) -> PlannedWorkItem:
        return PlannedWorkItem(
            work_id="build-thread-001",
            title="Carry bounded maintenance forward",
            description="Keep a single small build thread active instead of idling.",
            mode="build",
            state="proposed",
            priority=1,
            route="safe",
            related_files=[
                "src/the_daddy/engine.py",
                "src/the_daddy/agents/improvement_planner.py",
                "src/the_daddy/merge_rules.py",
            ],
            notes=[
                "Prefer bounded code patches over doc-only churn.",
                "Do not broaden scope when verification is failing.",
            ],
        )

    def _derive_build_action(self, review: ArchitectureReview) -> PlannedWorkItem | None:
        if not review.self_evolution_actions:
            return None

        first_action = review.self_evolution_actions[0]
        related_files = [self._normalize_path(patch.path) for patch in first_action.patches if getattr(patch, "path", "")]
        if not related_files:
            return None

        title = first_action.title.strip() or "Carry bounded maintenance forward"
        description = first_action.description.strip() or "Apply the bounded self-evolution patch set."

        notes = [
            "Derived from reviewer-proposed self-evolution action.",
            "Keep the change bounded and verification-driven.",
        ]

        return PlannedWorkItem(
            work_id="build-thread-derived-001",
            title=title[:120],
            description=description[:500],
            mode="build",
            state="proposed",
            priority=1,
            route="safe",
            related_files=related_files[:8],
            notes=notes,
        )

    def _default_architecture_plan(self, repo_root: Path) -> ArchitecturePlan | None:
        target = repo_root / "src" / "the_daddy" / "runtime" / "architecture_probe.py"
        if target.exists():
            return None

        new_content = '''from __future__ import annotations

from typing import Any


def architecture_probe_summary(summary: str, files_touched: list[str] | None = None) -> dict[str, Any]:
    return {
        "summary": summary,
        "files_touched": files_touched or [],
        "source": "architecture_probe",
    }
'''
        patch = PatchAction(
            path=ARCHITECTURE_RUNTIME_PATH,
            operation="replace_file",
            new_content=new_content,
            description="Add a bounded architecture probe helper in a non-protected runtime path.",
        )
        return ArchitecturePlan(
            title="Branch-only bounded runtime architecture probe",
            summary="Stage one bounded branch-safe runtime helper for architecture-lane observability.",
            rationale="Architecture mode must emit a real patch bundle that does not target protected core files.",
            route="branch",
            files_touched=[ARCHITECTURE_RUNTIME_PATH],
            patch_bundle=[patch],
            status="proposed",
        )

    def _build_prompt(
        self,
        memory_snapshot: dict[str, Any],
        repo_snapshot: dict[str, Any],
        recent_summary: str,
    ) -> str:
        memory_json = json.dumps(memory_snapshot, indent=2)[:18000]
        repo_json = json.dumps(repo_snapshot, indent=2)[:26000]

        allowlisted_new_files = "\n".join(f"  * {path}" for path in sorted(SAFE_NEW_FILE_ALLOWLIST))
        banned_paths = "\n".join(f"  * {path}" for path in sorted(BANNED_SELF_EVOLUTION_PATHS))

        return f"""You are the wake-review agent for a bounded self-maintenance repository.

Return valid JSON only.

Rules:
- Output MUST match the requested schema exactly.
- Prefer one small executable Python patch over documentation-only output when possible.
- Only emit safe, bounded changes.
- Never emit secrets handling, destructive shell commands, dependency explosions, or large rewrites.
- If you emit any self_evolution_actions, also emit at least one matching build_action that describes carrying that patch set forward.
- Only emit architecture_plans when there is a genuine repo-wide structural issue that should be handled in a branch lane.
- If there is no justified architecture plan, return an empty architecture_plans array.
- Keep build_actions concrete, file-aware, and aligned to the self_evolution_actions when present.
- Do not invent architecture work just to fill the field.
- Avoid repetitive low-value maintenance loops.
- NEVER propose any wake-review invariant test, wake-review output test, wake-review contract test, or self-evolution action existence test.
- NEVER propose tests targeting:
  * tests/test_wake_review_invariant.py
  * tests/test_wake_review_invariants.py
  * tests/test_wake_review_output.py
  * tests/test_wake_review_contract.py
  * tests/test_self_evolution.py
- Do not propose a new regression test if a materially similar test already exists in tests/.
- Do not repeat backlog items that are already present in memory unless there is genuinely new evidence.
- Treat these as permanently banned low-value loops:
  * wake-review invariant test
  * wake-review output test
  * wake-review contract test
  * self-evolution action existence test
- Prefer source/runtime fixes over another tiny documentation or test-only loop when the system is already green.
- Even when the repo is green, proactively propose one bounded runtime, observability, or safety improvement if a non-repetitive one exists.
- Prefer runtime/observability helpers over tests when no failures exist.
- CRITICAL: every self_evolution patch path MUST be either:
  * an existing tracked file from the repository snapshot, or
  * one of these allowlisted new files only:
{allowlisted_new_files}
- CRITICAL: NEVER target these banned self-evolution paths:
{banned_paths}
- NEVER invent a new module name like logging_utils.py, reviewer.py, helper.py, utils.py, or similar unless that exact path already exists in tracked_files.
- If you cannot justify a patch against an existing tracked file, use one of the allowlisted runtime helper paths above.
- If no valid self_evolution patch target exists, return an empty self_evolution_actions array.

Required JSON shape:
{{
  "diagnosis": "string",
  "system_intent": "string",
  "strengths": ["string"],
  "weaknesses": ["string"],
  "recommendations": ["string"],
  "backlog_items": ["string"],
  "self_evolution_actions": [
    {{
      "title": "string",
      "description": "string",
      "risk": "safe",
      "patches": [
        {{
          "path": "string",
          "operation": "replace_file",
          "new_content": "string",
          "pattern": null,
          "replacement": null,
          "description": "string"
        }}
      ]
    }}
  ],
  "build_actions": [
    {{
      "work_id": "string",
      "title": "string",
      "description": "string",
      "mode": "build",
      "state": "proposed",
      "priority": 1,
      "route": "safe",
      "related_files": ["string"],
      "notes": ["string"],
      "created_at": "ISO timestamp",
      "updated_at": "ISO timestamp"
    }}
  ],
  "architecture_plans": [
    {{
      "title": "string",
      "summary": "string",
      "rationale": "string",
      "route": "branch",
      "files_touched": ["string"],
      "patch_bundle": [
        {{
          "path": "string",
          "operation": "replace_file",
          "new_content": "string",
          "pattern": null,
          "replacement": null,
          "description": "string"
        }}
      ],
      "proof_requirements": ["string"],
      "status": "proposed",
      "created_at": "ISO timestamp",
      "updated_at": "ISO timestamp"
    }}
  ],
  "execution_notes": ["string"],
  "risk_level": "low"
}}

Recent summary:
{recent_summary}

Current memory snapshot:
{memory_json}

Repository snapshot:
{repo_json}
"""

    def _fallback_review(self, repo_root: Path, reason: str) -> ArchitectureReview:
        proactive_action = self._proactive_runtime_action(repo_root)
        fallback_action = self._fallback_patch_action(repo_root)
        fallback_plan = self._default_architecture_plan(repo_root)

        actions: list[SelfEvolutionAction] = []
        if proactive_action is not None:
            actions.append(proactive_action)
        elif fallback_action is not None:
            actions.append(fallback_action)

        plans = [fallback_plan] if fallback_plan is not None else []

        execution_notes = ["Fallback review used because model output was unavailable or invalid."]
        if proactive_action is not None:
            execution_notes.append("Proactive runtime improvement injected while repo is otherwise healthy.")

        return ArchitectureReview(
            diagnosis="Fallback review generated",
            system_intent="Keep the agent bounded, testable, patch-capable, proactive, and anti-loop.",
            strengths=["Repository is reachable and reviewer fallback is active."],
            weaknesses=[reason],
            recommendations=["Stabilise reviewer schema and runtime alignment."],
            backlog_items=["Tighten schema alignment between reviewer, planner, and engine."],
            self_evolution_actions=actions,
            build_actions=[self._default_build_action()],
            architecture_plans=plans,
            execution_notes=execution_notes,
            risk_level="low",
        )

    def review(self, memory_snapshot: dict[str, Any], repo_root: Path, recent_summary: str) -> ArchitectureReview:
        if self.client is None:
            return self._fallback_review(repo_root, "OpenAI client unavailable.")

        repo_snapshot = self._repo_snapshot(repo_root)
        prompt = self._build_prompt(memory_snapshot, repo_snapshot, recent_summary)

        try:
            data = self.client.generate_json(
                model=self.settings.openai_model_review,
                system=(
                    "You are a strict JSON-only architecture reviewer. "
                    "Return only a valid JSON object matching the provided schema. "
                    "When you propose a self-evolution action, include a matching build_action. "
                    "Only include architecture_plans when clearly justified by a repo-wide structural issue. "
                    "Avoid repetitive low-value test or backlog churn. "
                    "Never propose wake-review invariant/output/contract tests or self-evolution existence tests. "
                    "Do not invent new file targets unless they are explicitly allowlisted runtime helper paths. "
                    "Do not target banned self-evolution paths. "
                    "When the repo is green, still look for one bounded runtime, observability, or safety improvement."
                ),
                prompt=prompt,
                schema=ArchitectureReview.model_json_schema(),
            )
            review = ArchitectureReview.model_validate(data)
        except Exception as exc:
            print(f"[REVIEWER ERROR] {type(exc).__name__}: {exc}", flush=True)
            return self._fallback_review(repo_root, f"Reviewer model call failed: {type(exc).__name__}: {exc}")

        tracked_files = repo_snapshot.get("tracked_files", []) or []
        filtered_actions, action_notes = self._filter_low_value_actions(
            review.self_evolution_actions,
            tracked_files,
        )
        review.self_evolution_actions = filtered_actions
        if action_notes:
            review.execution_notes.extend(action_notes)

        filtered_backlog, removed_backlog = self._filter_repetitive_backlog_items(
            review.backlog_items,
            memory_snapshot,
        )
        review.backlog_items = filtered_backlog
        if removed_backlog:
            review.execution_notes.append("Suppressed repetitive backlog items already present in memory.")

        if not review.build_actions:
            derived_action = self._derive_build_action(review)
            if derived_action is not None:
                review.build_actions = [derived_action]
                review.execution_notes.append("Derived build action injected from reviewer-proposed self-evolution patch set.")
            else:
                review.build_actions = [self._default_build_action()]
                review.execution_notes.append("Default build action injected because reviewer returned none.")

        if not review.self_evolution_actions:
            proactive_action = self._proactive_runtime_action(repo_root)
            if proactive_action is not None:
                review.self_evolution_actions = [proactive_action]
                review.execution_notes.append(
                    "Proactive runtime improvement injected while repo is green."
                )
            else:
                fallback_action = self._fallback_patch_action(repo_root)
                if fallback_action is not None:
                    review.self_evolution_actions = [fallback_action]
                    review.execution_notes.append(
                        "Fallback self-evolution patch injected because reviewer returned no executable patch."
                    )

        if review.architecture_plans:
            justified_plans: list[ArchitecturePlan] = []
            for plan in review.architecture_plans:
                valid_paths = [
                    self._normalize_path(path)
                    for path in (plan.files_touched or [])
                    if self._is_allowed_patch_path(path, tracked_files)
                ]
                valid_bundle = [
                    patch
                    for patch in (plan.patch_bundle or [])
                    if self._is_allowed_patch_path(getattr(patch, "path", ""), tracked_files)
                ]
                if valid_paths and valid_bundle:
                    plan.files_touched = valid_paths
                    plan.patch_bundle = valid_bundle
                    justified_plans.append(plan)
            review.architecture_plans = justified_plans

        return review
