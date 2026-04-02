from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openai import OpenAI

from ..config import Settings
from ..models import (
    ArchitecturePlan,
    ArchitectureReview,
    PatchAction,
    PlannedWorkItem,
    SelfEvolutionAction,
)


class WakeReviewer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key)

    def _repo_snapshot(self, repo_root: Path) -> dict[str, Any]:
        tracked: list[str] = []
        preview_files: list[dict[str, str]] = []

        ignored_parts = {".git", ".venv", "__pycache__", "doctor_local", ".pytest_cache", "build", "dist"}

        for path in sorted(repo_root.rglob("*")):
            if not path.is_file():
                continue

            rel = str(path.relative_to(repo_root))
            if any(part in ignored_parts for part in path.parts):
                continue

            tracked.append(rel)

            if len(preview_files) < 50 and path.suffix in {".py", ".md", ".yml", ".yaml", ".toml", ".json"}:
                try:
                    preview_files.append(
                        {
                            "path": rel,
                            "content_preview": path.read_text(encoding="utf-8", errors="ignore")[:8000],
                        }
                    )
                except Exception:
                    continue

            if len(tracked) >= 300:
                break

        return {
            "tracked_files": tracked,
            "preview_files": preview_files,
        }

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    def _doc_fallback_action(self, repo_root: Path) -> SelfEvolutionAction:
        architecture_path = repo_root / "ARCHITECTURE.md"
        marker = (
            "\n\n## Wake Review Forced Architecture Output\n"
            "- Architecture plans must include a non-empty patch bundle when branch execution is requested.\n"
            "- If no safe multi-file architecture bundle is available, the reviewer should emit a bounded documentation patch and a smaller build action instead of returning an empty architecture bundle.\n"
        )

        if architecture_path.exists():
            current = self._read_text(architecture_path)
            if "## Wake Review Forced Architecture Output" not in current:
                return SelfEvolutionAction(
                    title="Document forced architecture patch output",
                    description="Record that architecture planning must not return empty patch bundles.",
                    risk="safe",
                    patches=[
                        PatchAction(
                            path="ARCHITECTURE.md",
                            operation="replace_file",
                            new_content=current + marker,
                            description="Append forced architecture output notes to architecture documentation.",
                        )
                    ],
                )

        readme_path = repo_root / "README.md"
        readme = self._read_text(readme_path)
        if "Wake-review forced architecture output" not in readme:
            return SelfEvolutionAction(
                title="Document forced architecture output in README",
                description="Add a bounded README note explaining that architecture plans must include executable patch bundles.",
                risk="safe",
                patches=[
                    PatchAction(
                        path="README.md",
                        operation="replace_file",
                        new_content=readme
                        + "\n\n### Wake-review forced architecture output\nArchitecture plans must include executable patch bundles when branch execution is requested.\n",
                        description="Append forced architecture output note to README.",
                    )
                ],
            )

        return SelfEvolutionAction(
            title="No fallback target available",
            description="No safe documentation target was available for forced-output fallback.",
            risk="recommend",
            patches=[],
        )

    def _default_build_action(self) -> PlannedWorkItem:
        return PlannedWorkItem(
            work_id="build-thread-001",
            title="Carry forward bounded reliability improvements",
            description="Continue a small reliability build thread across runs instead of treating every run as a one-off.",
            mode="build",
            state="proposed",
            priority=1,
            route="safe",
            related_files=[
                "src/the_daddy/engine.py",
                "src/the_daddy/memory/repository.py",
                "src/the_daddy/agents/reviewer.py",
            ],
            notes=[
                "Continue only one bounded build thread per cycle.",
                "Stop feature work if tests fail.",
            ],
        )

    def _default_architecture_plan(self, repo_root: Path) -> ArchitecturePlan:
        architecture_path = repo_root / "ARCHITECTURE.md"
        current = self._read_text(architecture_path)
        if "## Branch Architecture Execution" not in current:
            new_content = current + (
                "\n\n## Branch Architecture Execution\n"
                "- Architecture mode may stage branch-only multi-file plans.\n"
                "- A valid architecture plan must include an executable patch bundle.\n"
                "- Safe branch execution should prefer reviewable documentation or metadata scaffolding before larger code rewrites.\n"
            )
        else:
            new_content = current

        patch_bundle = []
        if new_content != current:
            patch_bundle.append(
                PatchAction(
                    path="ARCHITECTURE.md",
                    operation="replace_file",
                    new_content=new_content,
                    description="Add branch architecture execution notes so architecture mode always has an executable starter bundle.",
                )
            )

        return ArchitecturePlan(
            title="Branch-only architecture hardening plan",
            summary="Stage a branch-only architecture starter patch so architecture mode can actually execute instead of idling.",
            rationale="The architecture lane should never queue an empty patch bundle because that blocks branch creation, PR creation, and merge flow.",
            route="branch",
            files_touched=["ARCHITECTURE.md"] if patch_bundle else [],
            patch_bundle=patch_bundle,
            status="proposed",
        )

    def _build_prompt(self, memory_snapshot: dict[str, Any], repo_root: Path, recent_summary: str) -> str:
        repo_snapshot = self._repo_snapshot(repo_root)
        memory_json = json.dumps(memory_snapshot, indent=2)[:24000]
        repo_json = json.dumps(repo_snapshot, indent=2)[:36000]

        return f"""You are the wake-review architecture agent for a bounded defensive repository-maintenance system.

You are operating in FORCED ARCHITECTURE OUTPUT mode.

Mission on every run:
1. audit the current repository and memory state
2. identify structural weaknesses, repeated drift, and concrete bounded opportunities
3. emit executable self-evolution patches
4. emit one bounded build action when useful
5. emit one branch-only architecture plan with a NON-EMPTY patch bundle whenever architecture planning is appropriate

Hard rules:
- Do NOT return an idle cycle if a safe bounded patch is possible.
- Prefer real low-risk code patches when a concrete mismatch or missing helper is visible.
- If no safe code patch is justified, emit a documentation fallback patch instead.
- SelfEvolutionAction objects MUST contain explicit PatchAction objects in `patches`.
- ArchitecturePlan must be branch-only and MUST include a non-empty `patch_bundle` when returned.
- An empty architecture patch bundle is invalid output for this system.
- Build actions should be small, continuable, and safe.
- Avoid secrets, destructive shell commands, dependency explosions, policy bypass, infrastructure changes, or broad rewrites.
- Keep everything bounded and reviewable.

Return valid JSON only using this exact schema:
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
          "path": "src/the_daddy/some_file.py",
          "operation": "replace_file",
          "new_content": "full file content here",
          "pattern": null,
          "replacement": null,
          "description": "why this patch is needed"
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
      "created_at": "ISO timestamp string",
      "updated_at": "ISO timestamp string"
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
          "path": "ARCHITECTURE.md",
          "operation": "replace_file",
          "new_content": "full file content here",
          "pattern": null,
          "replacement": null,
          "description": "why this patch is needed"
        }}
      ],
      "proof_requirements": ["string"],
      "status": "proposed",
      "created_at": "ISO timestamp string",
      "updated_at": "ISO timestamp string"
    }}
  ],
  "execution_notes": ["string"],
  "risk_level": "low|medium|high",
  "reviewed_at": "ISO timestamp string"
}}

Current memory snapshot:
{memory_json}

Recent summary:
{recent_summary}

Repository snapshot:
{repo_json}
"""

    def _parse_response(self, text: str) -> dict[str, Any]:
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise
            return json.loads(text[start : end + 1])

    def review(self, memory_snapshot: dict[str, Any], repo_root: Path, recent_summary: str) -> ArchitectureReview:
        prompt = self._build_prompt(memory_snapshot, repo_root, recent_summary)

        response = self.client.responses.create(
            model=self.settings.openai_model_review,
            input=prompt,
        )

        data = self._parse_response(response.output_text)
        review = ArchitectureReview.model_validate(data)

        valid_actions: list[SelfEvolutionAction] = []
        for action in review.self_evolution_actions:
            if action.patches:
                valid_actions.append(action)

        if not valid_actions:
            fallback = self._doc_fallback_action(repo_root)
            if fallback.patches:
                valid_actions = [fallback]
                review.execution_notes.append(
                    "Fallback self-evolution patch injected because the model returned no executable patches."
                )
                if "Wake reviewer returned no executable patches." not in review.weaknesses:
                    review.weaknesses.append("Wake reviewer returned no executable patches.")
                if "Improve reviewer forced-output reliability." not in review.backlog_items:
                    review.backlog_items.append("Improve reviewer forced-output reliability.")

        review.self_evolution_actions = valid_actions

        if not review.build_actions:
            review.build_actions = [self._default_build_action()]
            review.execution_notes.append(
                "Default bounded build action injected so the system can carry work across runs."
            )

        valid_architecture_plans: list[ArchitecturePlan] = []
        for plan in review.architecture_plans:
            if plan.patch_bundle:
                valid_architecture_plans.append(plan)

        if not valid_architecture_plans:
            default_plan = self._default_architecture_plan(repo_root)
            if default_plan.patch_bundle:
                valid_architecture_plans = [default_plan]
                review.execution_notes.append(
                    "Default architecture plan with executable patch bundle injected because the model returned no valid branch bundle."
                )
                if "Wake reviewer returned empty architecture patch bundles." not in review.weaknesses:
                    review.weaknesses.append("Wake reviewer returned empty architecture patch bundles.")
                if "Improve architecture patch-bundle generation reliability." not in review.backlog_items:
                    review.backlog_items.append("Improve architecture patch-bundle generation reliability.")

        review.architecture_plans = valid_architecture_plans

        return review