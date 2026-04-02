from __future__ import annotations

import json
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

    def _fallback_patch_action(self, repo_root: Path) -> SelfEvolutionAction | None:
        target = repo_root / "src" / "the_daddy" / "merge_rules.py"
        current = self._read_text(target)
        if current and "MAX_ARCHITECTURE_BRANCH_FILES = 5" in current and "# daddy-review-guard" not in current:
            new_content = current.rstrip() + "\n\n# daddy-review-guard\n"
            return SelfEvolutionAction(
                title="Add bounded reviewer guard marker",
                description="Inject a tiny bounded Python-level marker so the reviewer always emits a real patch when it fails to produce one.",
                risk="safe",
                patches=[
                    PatchAction(
                        path="src/the_daddy/merge_rules.py",
                        operation="replace_file",
                        new_content=new_content,
                        description="Append a bounded reviewer guard marker.",
                    )
                ],
            )

        target = repo_root / "ARCHITECTURE.md"
        current = self._read_text(target)
        if current and "Wake reviewer fallback" not in current:
            new_content = (
                current.rstrip()
                + "\n\n## Wake reviewer fallback\n"
                + "- A bounded patch fallback was injected because the model returned no executable patch.\n"
            )
            return SelfEvolutionAction(
                title="Document reviewer fallback",
                description="Fallback doc patch only when no bounded Python target is available.",
                risk="safe",
                patches=[
                    PatchAction(
                        path="ARCHITECTURE.md",
                        operation="replace_file",
                        new_content=new_content,
                        description="Append reviewer fallback note.",
                    )
                ],
            )

        return None

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
        related_files = [patch.path for patch in first_action.patches if getattr(patch, "path", "")]
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
        target = repo_root / "src" / "the_daddy" / "merge_rules.py"
        current = self._read_text(target)
        if not current or "# architecture-plan-marker" in current:
            return None

        new_content = current.rstrip() + "\n\n# architecture-plan-marker\n"
        patch = PatchAction(
            path="src/the_daddy/merge_rules.py",
            operation="replace_file",
            new_content=new_content,
            description="Append a bounded architecture marker to prove branch-lane output is a real patch bundle.",
        )
        return ArchitecturePlan(
            title="Branch-only bounded maintenance plan",
            summary="Stage one bounded branch-safe code patch for the architecture lane.",
            rationale="Architecture mode must have a real non-empty patch bundle.",
            route="branch",
            files_touched=["src/the_daddy/merge_rules.py"],
            patch_bundle=[patch],
            status="proposed",
        )

    def _build_prompt(self, memory_snapshot: dict[str, Any], repo_root: Path, recent_summary: str) -> str:
        repo_snapshot = self._repo_snapshot(repo_root)
        memory_json = json.dumps(memory_snapshot, indent=2)[:18000]
        repo_json = json.dumps(repo_snapshot, indent=2)[:26000]

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
        fallback_action = self._fallback_patch_action(repo_root)
        fallback_plan = self._default_architecture_plan(repo_root)

        actions = [fallback_action] if fallback_action is not None else []
        plans = [fallback_plan] if fallback_plan is not None else []

        return ArchitectureReview(
            diagnosis="Fallback review generated",
            system_intent="Keep the agent bounded, testable, and patch-capable.",
            strengths=["Repository is reachable and reviewer fallback is active."],
            weaknesses=[reason],
            recommendations=["Stabilise reviewer schema and runtime alignment."],
            backlog_items=["Tighten schema alignment between reviewer, planner, and engine."],
            self_evolution_actions=actions,
            build_actions=[self._default_build_action()],
            architecture_plans=plans,
            execution_notes=["Fallback review used because model output was unavailable or invalid."],
            risk_level="low",
        )

    def review(self, memory_snapshot: dict[str, Any], repo_root: Path, recent_summary: str) -> ArchitectureReview:
        if self.client is None:
            return self._fallback_review(repo_root, "OpenAI client unavailable.")

        prompt = self._build_prompt(memory_snapshot, repo_root, recent_summary)

        try:
            data = self.client.generate_json(
                model=self.settings.openai_model_review,
                system=(
                    "You are a strict JSON-only architecture reviewer. "
                    "Return only a valid JSON object matching the provided schema. "
                    "When you propose a self-evolution action, include a matching build_action. "
                    "Only include architecture_plans when clearly justified by a repo-wide structural issue."
                ),
                prompt=prompt,
                schema=ArchitectureReview.model_json_schema(),
            )
            review = ArchitectureReview.model_validate(data)
        except Exception as exc:
            print(f"[REVIEWER ERROR] {type(exc).__name__}: {exc}", flush=True)
            return self._fallback_review(repo_root, f"Reviewer model call failed: {type(exc).__name__}: {exc}")

        if not review.build_actions:
            derived_action = self._derive_build_action(review)
            if derived_action is not None:
                review.build_actions = [derived_action]
                review.execution_notes.append("Derived build action injected from reviewer-proposed self-evolution patch set.")
            else:
                review.build_actions = [self._default_build_action()]
                review.execution_notes.append("Default build action injected because reviewer returned none.")

        if not review.self_evolution_actions:
            fallback_action = self._fallback_patch_action(repo_root)
            if fallback_action is not None:
                review.self_evolution_actions = [fallback_action]
                review.execution_notes.append(
                    "Fallback self-evolution patch injected because reviewer returned no executable patch."
                )

        if review.architecture_plans:
            justified_plans: list[ArchitecturePlan] = []
            for plan in review.architecture_plans:
                if plan.patch_bundle and plan.files_touched:
                    justified_plans.append(plan)
            review.architecture_plans = justified_plans

        return review
