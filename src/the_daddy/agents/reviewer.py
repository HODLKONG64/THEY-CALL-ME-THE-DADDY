from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import Settings
from ..models import ArchitectureReview, PatchAction
from ..prompts import ARCHITECTURE_REVIEW_SYSTEM
from .openai_client import OpenAIJSONClient

REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "diagnosis": {"type": "string"},
        "system_intent": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "weaknesses": {"type": "array", "items": {"type": "string"}},
        "recommendations": {"type": "array", "items": {"type": "string"}},
        "backlog_items": {"type": "array", "items": {"type": "string"}},
        "self_evolution_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string"},
                    "operation": {"type": "string", "enum": ["replace_file", "regex_replace"]},
                    "description": {"type": "string"},
                    "new_content": {"type": ["string", "null"]},
                    "pattern": {"type": ["string", "null"]},
                    "replacement": {"type": ["string", "null"]},
                },
                "required": [
                    "path",
                    "operation",
                    "description",
                    "new_content",
                    "pattern",
                    "replacement",
                ],
            },
        },
        "execution_notes": {"type": "array", "items": {"type": "string"}},
        "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": [
        "diagnosis",
        "system_intent",
        "strengths",
        "weaknesses",
        "recommendations",
        "backlog_items",
        "self_evolution_actions",
        "execution_notes",
        "risk_level",
    ],
}

KEY_FILES = [
    "README.md",
    ".env.example",
    ".github/workflows/daddy-cycle.yml",
    "src/the_daddy/engine.py",
    "src/the_daddy/prompts.py",
    "src/the_daddy/config.py",
    "src/the_daddy/agents/improvement_planner.py",
    "src/the_daddy/agents/reviewer.py",
    "src/the_daddy/policy.py",
    "src/the_daddy/models.py",
    "tests/test_self_evolution.py",
]


class WakeReviewer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAIJSONClient(settings)

    def _repo_tree(self, repo_root: Path) -> list[str]:
        paths: list[str] = []
        ignored = {".git", ".venv", "venv", "node_modules", "__pycache__", "doctor_local"}
        for path in sorted(repo_root.rglob("*")):
            if path.is_dir():
                continue
            if any(part in ignored for part in path.parts):
                continue
            rel = path.relative_to(repo_root).as_posix()
            paths.append(rel)
            if len(paths) >= 160:
                break
        return paths

    def _key_file_context(self, repo_root: Path) -> dict[str, str]:
        context: dict[str, str] = {}
        for rel in KEY_FILES:
            path = repo_root / rel
            if not path.exists() or not path.is_file():
                continue
            context[rel] = path.read_text(encoding="utf-8", errors="ignore")[:16000]
        return context

    def _build_status_content(
        self,
        *,
        review: ArchitectureReview,
        repo_tree: list[str],
        previous_content: str,
    ) -> str:
        strengths = review.strengths[:5] or ["No strengths recorded."]
        weaknesses = review.weaknesses[:5] or ["No weaknesses recorded."]
        recommendations = review.recommendations[:5] or ["No recommendations recorded."]
        backlog_items = review.backlog_items[:5] or review.recommendations[:5] or ["No backlog items recorded."]
        repo_sample = repo_tree[:20] or ["No repo files sampled."]

        previous_tail = ""
        if previous_content.strip():
            previous_tail = (
                "\n## Previous Artifact Detected\n\n"
                "A prior version of this file existed. The current wake cycle replaced it with a refreshed audited snapshot.\n"
            )

        return (
            "# Self-Evolution Status\n\n"
            "This file is maintained by the wake reviewer so every healthy wake cycle leaves a small, safe, auditable artifact in the repo.\n\n"
            f"## Reviewed At\n\n{review.reviewed_at}\n\n"
            f"## Risk Level\n\n{review.risk_level}\n\n"
            "## System Intent\n\n"
            f"{review.system_intent or 'No explicit system intent returned.'}\n\n"
            "## Diagnosis\n\n"
            f"{review.diagnosis}\n\n"
            "## Top Strengths\n\n"
            + "\n".join(f"- {item}" for item in strengths)
            + "\n\n## Top Weaknesses\n\n"
            + "\n".join(f"- {item}" for item in weaknesses)
            + "\n\n## Current Recommendations\n\n"
            + "\n".join(f"- {item}" for item in recommendations)
            + "\n\n## Backlog Focus\n\n"
            + "\n".join(f"- {item}" for item in backlog_items)
            + "\n\n## Repo Sample\n\n"
            + "\n".join(f"- {item}" for item in repo_sample)
            + previous_tail
        )

    def _fallback_action(
        self,
        *,
        review: ArchitectureReview,
        repo_root: Path,
        repo_tree: list[str],
    ) -> PatchAction:
        target = repo_root / "docs" / "self_evolution_status.md"
        existing = ""
        if target.exists() and target.is_file():
            existing = target.read_text(encoding="utf-8", errors="ignore")[:50000]

        new_content = self._build_status_content(
            review=review,
            repo_tree=repo_tree,
            previous_content=existing,
        )

        if existing.strip() == new_content.strip():
            new_content += (
                "\n## Wake Cycle Note\n\n"
                "- Artifact refreshed with unchanged analytical content to preserve an auditable self-evolution event.\n"
            )

        return PatchAction(
            path="docs/self_evolution_status.md",
            operation="replace_file",
            description=(
                "Write a safe self-evolution status artifact so each wake cycle produces at least one low-risk, "
                "auditable improvement without modifying runtime logic."
            ),
            new_content=new_content,
            pattern=None,
            replacement=None,
        )

    def _normalize_review_lists(self, review: ArchitectureReview) -> None:
        if not review.strengths:
            review.strengths = ["Wake review completed successfully."]
        if not review.weaknesses:
            review.weaknesses = ["No explicit weakness list was returned."]
        if not review.recommendations:
            review.recommendations = ["Maintain bounded low-risk self-evolution with auditable artifacts."]
        if not review.backlog_items:
            review.backlog_items = list(review.recommendations[:5])
        if not review.execution_notes:
            review.execution_notes = ["Wake review completed under bounded defensive rules."]

    def _ensure_actionable_review(
        self,
        review: ArchitectureReview,
        *,
        repo_root: Path,
        repo_tree: list[str],
    ) -> ArchitectureReview:
        self._normalize_review_lists(review)
        safe_actions: list[PatchAction] = []

        for action in review.self_evolution_actions:
            path = action.path.strip()
            if not path:
                continue
            if action.operation == "replace_file" and action.new_content is None:
                continue
            if action.operation == "regex_replace" and (action.pattern is None or action.replacement is None):
                continue
            lowered = path.lower()
            if lowered.endswith(":"):
                continue
            if any(fragment in lowered for fragment in [".env", "secret", "token", "credential"]):
                continue
            safe_actions.append(action)

        review.self_evolution_actions = safe_actions

        if review.self_evolution_actions:
            if review.risk_level == "high":
                review.risk_level = "medium"
            return review

        review.self_evolution_actions = [
            self._fallback_action(review=review, repo_root=repo_root, repo_tree=repo_tree)
        ]
        review.execution_notes.append(
            "No bounded patchable action was returned by the model, so the reviewer generated a safe documentation artifact to keep self-evolution active and auditable."
        )
        if review.risk_level == "high":
            review.risk_level = "medium"
        return review

    def _build_prompt(
        self,
        *,
        repo_root: Path,
        repo_tree: list[str],
        key_file_context: dict[str, str],
        memory_snapshot: dict[str, Any],
        recent_summary: str,
    ) -> str:
        return (
            f"Repo root: {repo_root}\n"
            f"Recent summary: {recent_summary or 'None'}\n"
            f"Maintenance command: {self.settings.maintenance_command}\n"
            f"Current command: {self.settings.command}\n"
            f"Repo tree: {json.dumps(repo_tree)[:45000]}\n"
            f"Key file context: {json.dumps(key_file_context)[:120000]}\n"
            f"Memory snapshot: {json.dumps(memory_snapshot)[:50000]}\n\n"
            "Return strict JSON that matches the schema exactly.\n"
            "When the repository is healthy, you must still produce at least one low-risk self_evolution_action.\n"
            "Prefer a markdown or documentation artifact if you are not highly confident editing runtime code.\n"
            "Only generate bounded actions that fit the existing architecture and are safe to auto-apply.\n"
            "Do not leave self_evolution_actions empty.\n"
            "Do not suggest secrets changes, destructive commands, dependency explosions, or broad rewrites.\n"
        )

    def review(self, *, memory_snapshot: dict, repo_root: Path, recent_summary: str) -> ArchitectureReview:
        repo_tree = self._repo_tree(repo_root)
        key_file_context = self._key_file_context(repo_root)
        prompt = self._build_prompt(
            repo_root=repo_root,
            repo_tree=repo_tree,
            key_file_context=key_file_context,
            memory_snapshot=memory_snapshot,
            recent_summary=recent_summary,
        )
        data = self.client.generate_json(
            model=self.settings.openai_model_review,
            system=ARCHITECTURE_REVIEW_SYSTEM,
            prompt=prompt,
            schema=REVIEW_SCHEMA,
        )
        review = ArchitectureReview(**data)
        return self._ensure_actionable_review(review, repo_root=repo_root, repo_tree=repo_tree)
