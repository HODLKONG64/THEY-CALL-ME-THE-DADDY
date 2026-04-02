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

            if len(preview_files) < 60 and path.suffix in {".py", ".md", ".yml", ".yaml", ".toml", ".json"}:
                try:
                    preview_files.append(
                        {
                            "path": rel,
                            "content_preview": path.read_text(encoding="utf-8", errors="ignore")[:10000],
                        }
                    )
                except Exception:
                    continue

            if len(tracked) >= 350:
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

    def _default_python_patch_action(self, repo_root: Path) -> SelfEvolutionAction:
        target = repo_root / "src" / "the_daddy" / "merge_rules.py"
        current = self._read_text(target)

        if current and "MAX_SAFE_PATCH_COUNT" not in current:
            marker = (
                "\n\n# Builder-mode auto-merge tuning\n"
                "MAX_SAFE_PATCH_COUNT = 8\n"
            )
            return SelfEvolutionAction(
                title="Add builder-mode merge tuning constant",
                description="Add a bounded Python-level tuning constant so the system prefers meaningful small code changes over doc-only idle cycles.",
                risk="safe",
                patches=[
                    PatchAction(
                        path="src/the_daddy/merge_rules.py",
                        operation="replace_file",
                        new_content=current + marker,
                        description="Append a bounded Python constant to support builder-mode patch flow.",
                    )
                ],
            )

        target = repo_root / "src" / "the_daddy" / "agents" / "improvement_planner.py"
        current = self._read_text(target)
        if current and "architecture_plans_count" not in current:
            append = (
                "\n\n# Builder-mode note:\n"
                "# architecture_plans_count can be used by future planners to prefer branch execution when repeated safe code opportunities appear.\n"
            )
            return SelfEvolutionAction(
                title="Add planner builder-mode note",
                description="Emit a real Python patch instead of a documentation patch when no stronger bounded code change is identified.",
                risk="safe",
                patches=[
                    PatchAction(
                        path="src/the_daddy/agents/improvement_planner.py",
                        operation="replace_file",
                        new_content=current + append,
                        description="Append a bounded Python comment note to keep builder mode producing executable code patches.",
                    )
                ],
            )

        return self._doc_fallback_action(repo_root)

    def _doc_fallback_action(self, repo_root: Path) -> SelfEvolutionAction:
        architecture_path = repo_root / "ARCHITECTURE.md"
        marker = (
            "\n\n## Wake Review Real Patch Mode\n"
            "- The reviewer should prefer a bounded Python patch over documentation-only patches whenever a safe code change is visible.\n"
            "- Documentation fallback is allowed only when no safe Python patch target is available.\n"
        )

        current = self._read_text(architecture_path)
        if current and "## Wake Review Real Patch Mode" not in current:
            return SelfEvolutionAction(
                title="Document real patch mode",
                description="Record that reviewer output should prioritise executable Python patches over documentation fallbacks.",
                risk="safe",
                patches=[
                    PatchAction(
                        path="ARCHITECTURE.md",
                        operation="replace_file",
                        new_content=current + marker,
                        description="Append real patch mode note to architecture documentation.",
                    )
                ],
            )

        return SelfEvolutionAction(
            title="No fallback target available",
            description="No safe fallback target was available.",
            risk="recommend",
            patches=[],
        )

    def _default_build_action(self) -> PlannedWorkItem:
        return PlannedWorkItem(
            work_id="build-thread-001",
            title="Carry forward bounded builder-mode improvements",
            description="Continue a small builder thread across runs instead of idling after safe patch application.",
            mode="build",
            state="proposed",
            priority=1,
            route="safe",
            related_files=[
                "src/the_daddy/engine.py",
                "src/the_daddy/merge_rules.py",
                "src/the_daddy/agents/improvement_planner.py",
            ],
            notes=[
                "Prefer a real Python patch each run when safe.",
                "Stop feature work if tests fail.",
            ],
        )

    def _default_architecture_plan(self, repo_root: Path) -> ArchitecturePlan:
        target = repo_root / "src" / "the_daddy" / "merge_rules.py"
        current = self._read_text(target)
        new_content = current

        if current and "MAX_ARCHITECTURE_BRANCH_FILES" not in current:
            new_content = current + "\nMAX_ARCHITECTURE_BRANCH_FILES = 5\n"

        patch_bundle = []
        if current and new_content != current:
            patch_bundle.append(
                PatchAction(
                    path="src/the_daddy/merge_rules.py",
                    operation="replace_file",
                    new_content=new_content,
                    description="Add a bounded architecture-branch tuning constant so architecture lane produces a real Python patch bundle.",
                )
            )

        return ArchitecturePlan(
            title="Branch-only builder architecture plan",
            summary="Stage a real Python patch bundle for the architecture lane so branch execution produces meaningful code changes.",
            rationale="Architecture mode should create a branchable Python patch bundle instead of idling on documentation-only changes.",
            route="branch",
            files_touched=["src/the_daddy/merge_rules.py"] if patch_bundle else [],
            patch_bundle=patch_bundle,
            status="proposed",
        )

    def _build_prompt(self, memory_snapshot: dict[str, Any], repo_root: Path, recent_summary: str) -> str:
        repo_snapshot = self._repo_snapshot(repo_root)
        memory_json = json.dumps(memory_snapshot, indent=2)[:26000]
        repo_json = json.dumps(repo_snapshot, indent=2)[:42000]

        return f"""You are the wake-review architecture agent for a bounded defensive repository-maintenance system.

You are operating in REAL PATCH MODE.

Mission on every run:
1. audit the current repository and memory state
2. identify concrete bounded opportunities
3. emit executable self-evolution patches
4. emit one bounded build action when useful
5. emit one branch-only architecture plan with a NON-EMPTY patch bundle when architecture planning is appropriate

Hard rules:
- Prefer a REAL PYTHON PATCH over documentation-only patches whenever a safe low-risk code target is visible.
- Do NOT return an idle cycle if a safe bounded patch is possible.
- SelfEvolutionAction objects MUST contain explicit PatchAction objects in `patches`.
- ArchitecturePlan must be branch-only and MUST include a non-empty `patch_bundle` when returned.
- Prefer small `.py` edits such as constants, helper guards, comments that affect planner behavior, or bounded metadata changes.
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
          "path": "src/the_daddy/some_file.py",
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

        valid_actions: list[SelfEvolutionAction] = [a for a in review.self_evolution_actions if a.patches]
        if not valid_actions:
            fallback = self._default_python_patch_action(repo_root)
            if fallback.patches:
                valid_actions = [fallback]
                review.execution_notes.append(
                    "Fallback Python patch injected because the model returned no executable code patches."
                )
                if "Wake reviewer returned no executable Python patches." not in review.weaknesses:
                    review.weaknesses.append("Wake reviewer returned no executable Python patches.")
                if "Improve reviewer real patch generation reliability." not in review.backlog_items:
                    review.backlog_items.append("Improve reviewer real patch generation reliability.")

        review.self_evolution_actions = valid_actions

        if not review.build_actions:
            review.build_actions = [self._default_build_action()]
            review.execution_notes.append(
                "Default bounded build action injected so the system can carry builder work across runs."
            )

        valid_architecture_plans: list[ArchitecturePlan] = [p for p in review.architecture_plans if p.patch_bundle]
        if not valid_architecture_plans:
            default_plan = self._default_architecture_plan(repo_root)
            if default_plan.patch_bundle:
                valid_architecture_plans = [default_plan]
                review.execution_notes.append(
                    "Default architecture plan with executable Python patch bundle injected because the model returned no valid branch bundle."
                )
                if "Wake reviewer returned empty architecture patch bundles." not in review.weaknesses:
                    review.weaknesses.append("Wake reviewer returned empty architecture patch bundles.")
                if "Improve architecture Python patch-bundle generation reliability." not in review.backlog_items:
                    review.backlog_items.append("Improve architecture Python patch-bundle generation reliability.")

        review.architecture_plans = valid_architecture_plans

        return review
