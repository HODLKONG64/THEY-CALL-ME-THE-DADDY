from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openai import OpenAI

from ..config import Settings
from ..models import ArchitectureReview, PatchAction, SelfEvolutionAction


class WakeReviewer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key)

    def _repo_snapshot(self, repo_root: Path) -> dict[str, Any]:
        tracked: list[str] = []
        preview_files: list[dict[str, str]] = []

        for path in sorted(repo_root.rglob("*")):
            if not path.is_file():
                continue

            rel = str(path.relative_to(repo_root))
            if any(part in {".git", ".venv", "__pycache__", "doctor_local", ".pytest_cache"} for part in path.parts):
                continue

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

        return {
            "tracked_files": tracked,
            "preview_files": preview_files,
        }

    def _fallback_action(self, repo_root: Path) -> SelfEvolutionAction:
        architecture_path = repo_root / "ARCHITECTURE.md"
        marker = (
            "\n\n## Wake Review Aggressive Mode\n"
            "- The wake reviewer is allowed to emit small multi-file defensive code patches when a concrete bounded improvement is visible.\n"
            "- It should prefer executable code patches over documentation-only patches when confidence is medium or higher.\n"
            "- It must still avoid broad rewrites, dependency explosions, secrets, infra changes, or unbounded autonomy.\n"
        )

        if architecture_path.exists():
            try:
                current = architecture_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                current = ""
            if "## Wake Review Aggressive Mode" not in current:
                return SelfEvolutionAction(
                    title="Document aggressive wake-review mode",
                    description="Record the stronger code-patch posture in architecture docs when no bounded code patch is confidently available.",
                    risk="safe",
                    patches=[
                        PatchAction(
                            path="ARCHITECTURE.md",
                            operation="replace_file",
                            new_content=current + marker,
                            description="Append aggressive wake-review operating notes to architecture documentation.",
                        )
                    ],
                )

        readme_path = repo_root / "README.md"
        readme = ""
        if readme_path.exists():
            try:
                readme = readme_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                readme = ""
        if "Wake-review aggressive mode" not in readme:
            return SelfEvolutionAction(
                title="Document aggressive wake-review mode in README",
                description="Add a small README note documenting that wake review now prefers bounded executable code patches over documentation fallback.",
                risk="safe",
                patches=[
                    PatchAction(
                        path="README.md",
                        operation="replace_file",
                        new_content=readme + "\n\n### Wake-review aggressive mode\nThe wake reviewer now prefers bounded executable code patches, including small multi-file defensive fixes, when a concrete low-risk improvement is visible.\n",
                        description="Append aggressive wake-review note to README.",
                    )
                ],
            )

        return SelfEvolutionAction(
            title="No safe fallback available",
            description="No safe documentation target was available for fallback patching.",
            risk="recommend",
            patches=[],
        )

    def _build_prompt(self, memory_snapshot: dict[str, Any], repo_root: Path, recent_summary: str) -> str:
        repo_snapshot = self._repo_snapshot(repo_root)
        memory_json = json.dumps(memory_snapshot, indent=2)[:22000]
        repo_json = json.dumps(repo_snapshot, indent=2)[:30000]

        return f"""You are the wake-review architecture agent for a bounded defensive repository-maintenance system.

You are operating in AGGRESSIVE BUT BOUNDED mode.

Mission on every run:
1. audit the current repository and memory state
2. identify structural weaknesses, repeated drift, and small concrete defects
3. recommend improvements
4. emit at least one executable self-evolution action whenever a safe bounded patch is possible

Aggressive mode rules:
- Prefer REAL CODE PATCHES over documentation patches.
- You may emit SMALL MULTI-FILE PATCHES when they are tightly related and bounded.
- You may align naming mismatches, add missing helpers, add tiny defensive guard clauses, add repo fingerprints, add persistence metadata, add circuit-breaker checks, add drift signals, add commit-gating helpers, or fix clearly visible schema mismatches.
- Prefer medium-confidence bounded execution over passive advisory output.
- Avoid broad rewrites, dependency explosions, secrets, destructive shell commands, policy bypass, infrastructure mutations, or speculative architecture replacement.
- Keep every patch surgical, reviewable, and low-risk.
- If a code patch is possible, do not choose a doc patch instead.
- Only use documentation fallback when there is truly no concrete bounded code improvement visible.

Critical structure rules:
- Every self_evolution_action must contain explicit PatchAction objects in the `patches` field.
- A SelfEvolutionAction is not itself a patch.
- Every replace_file action must include the full new file content.
- Multi-file patches are allowed, but only if the files are directly connected to the same bounded fix.

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
        code_patch_found = False

        for action in review.self_evolution_actions:
            if not action.patches:
                continue
            valid_actions.append(action)
            for patch in action.patches:
                if str(patch.path).endswith(".py"):
                    code_patch_found = True

        if valid_actions:
            review.self_evolution_actions = valid_actions
            if code_patch_found:
                review.execution_notes.append(
                    "Wake reviewer emitted executable code patches in aggressive bounded mode."
                )
            else:
                review.execution_notes.append(
                    "Wake reviewer emitted executable patches, but they were not code patches."
                )
            return review

        fallback = self._fallback_action(repo_root)
        if fallback.patches:
            review.self_evolution_actions = [fallback]
            review.execution_notes.append(
                "Fallback patch injected because model returned no executable aggressive-mode patches."
            )
            if "Wake reviewer returned no executable aggressive-mode patches." not in review.weaknesses:
                review.weaknesses.append("Wake reviewer returned no executable aggressive-mode patches.")
            if "Improve aggressive wake reviewer patch generation reliability." not in review.backlog_items:
                review.backlog_items.append("Improve aggressive wake reviewer patch generation reliability.")
        else:
            review.execution_notes.append(
                "No safe fallback patch could be generated after empty aggressive-mode output."
            )

        return review
