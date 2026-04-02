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
            if len(preview_files) < 30 and path.suffix in {".py", ".md", ".yml", ".yaml", ".toml", ".json"}:
                try:
                    preview_files.append(
                        {
                            "path": rel,
                            "content_preview": path.read_text(encoding="utf-8", errors="ignore")[:4000],
                        }
                    )
                except Exception:
                    continue

            if len(tracked) >= 200:
                break

        return {
            "tracked_files": tracked,
            "preview_files": preview_files,
        }

    def _fallback_action(self, repo_root: Path) -> SelfEvolutionAction:
        architecture_path = repo_root / "ARCHITECTURE.md"
        marker = (
            "\n\n## Wake Review Auto-Improvement Notes\n"
            "- The system should prefer bounded low-risk code patches when it can identify a concrete mismatch.\n"
            "- If no low-risk code patch is available, the reviewer may emit a documentation patch instead of returning no action.\n"
        )

        if architecture_path.exists():
            try:
                current = architecture_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                current = ""
            if "## Wake Review Auto-Improvement Notes" not in current:
                return SelfEvolutionAction(
                    title="Document safe code-patch fallback",
                    description="Append a bounded wake-review note to architecture docs so the system records a safe improvement when no concrete low-risk code patch is available.",
                    risk="safe",
                    patches=[
                        PatchAction(
                            path="ARCHITECTURE.md",
                            operation="replace_file",
                            new_content=current + marker,
                            description="Append safe code-patch fallback notes to architecture documentation.",
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
        if "Wake-review safe code patch fallback" not in readme:
            return SelfEvolutionAction(
                title="Document wake-review code-patch fallback in README",
                description="Add a small README note documenting that wake review should emit a low-risk code patch when possible and a doc patch otherwise.",
                risk="safe",
                patches=[
                    PatchAction(
                        path="README.md",
                        operation="replace_file",
                        new_content=readme + "\n\n### Wake-review safe code patch fallback\nThe wake reviewer should emit a low-risk code patch when it can identify a concrete bounded improvement. If not, it should emit a documentation fallback rather than no patch.\n",
                        description="Append bounded wake-review code-patch fallback note to README.",
                    )
                ],
            )

        return SelfEvolutionAction(
            title="No-op safe fallback unavailable",
            description="No safe documentation target was available for fallback patching.",
            risk="recommend",
            patches=[],
        )

    def _build_prompt(self, memory_snapshot: dict[str, Any], repo_root: Path, recent_summary: str) -> str:
        repo_snapshot = self._repo_snapshot(repo_root)
        memory_json = json.dumps(memory_snapshot, indent=2)[:18000]
        repo_json = json.dumps(repo_snapshot, indent=2)[:24000]

        return f"""You are the wake-review architecture agent for a bounded defensive repository-maintenance system.

Your job on every run:
1. audit the current repository and memory state
2. identify structural strengths and weaknesses
3. recommend improvements
4. produce at least one bounded self-evolution action whenever a safe explicit patch can be proposed

Primary objective:
- Prefer a REAL LOW-RISK CODE PATCH over a documentation patch when you can identify a concrete mismatch, missing method, naming inconsistency, small defensive guard, safe helper, or similar bounded improvement.
- Only fall back to docs if you truly cannot justify a concrete low-risk code edit.

Critical rules:
- DO NOT return empty self_evolution_actions unless there is truly no safe bounded patch possible.
- Every self_evolution_action must contain explicit PatchAction objects in the field `patches`.
- A SelfEvolutionAction is NOT a patch by itself. The engine executes the nested `patches`.
- Prefer surgical code fixes in existing Python files when:
  - a method name mismatch is visible
  - a missing helper is obvious
  - a return-shape mismatch is obvious
  - a safe guard clause can prevent known runtime failure
  - a tiny schema alignment fix is visible
- Keep code patches SMALL and BOUNDED.
- Avoid broad rewrites, secrets, destructive shell commands, policy bypass, dependency explosions, infra changes, or speculative architecture replacement.
- If you propose code changes, keep them surgical and low-risk.
- If you cannot justify a code patch, return a documentation fallback patch instead of no patch.

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
        for action in review.self_evolution_actions:
            if action.patches:
                valid_actions.append(action)

        if valid_actions:
            review.self_evolution_actions = valid_actions
            review.execution_notes.append(
                "Wake reviewer emitted executable self-evolution patches with code-first preference."
            )
            return review

        fallback = self._fallback_action(repo_root)
        if fallback.patches:
            review.self_evolution_actions = [fallback]
            review.execution_notes.append(
                "Fallback safe patch injected because model returned no executable patches."
            )
            if "Wake reviewer returned no executable patches." not in review.weaknesses:
                review.weaknesses.append("Wake reviewer returned no executable patches.")
            if "Improve wake reviewer code-patch generation reliability." not in review.backlog_items:
                review.backlog_items.append("Improve wake reviewer code-patch generation reliability.")
        else:
            review.execution_notes.append(
                "No safe fallback patch could be generated after empty self-evolution output."
            )

        return review