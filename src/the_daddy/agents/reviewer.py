from __future__ import annotations

import json
from pathlib import Path

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
                "required": ["path", "operation", "description", "new_content", "pattern", "replacement"],
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
]


class WakeReviewer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAIJSONClient(settings)

    def _repo_tree(self, repo_root: Path) -> list[str]:
        paths: list[str] = []
        for path in sorted(repo_root.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(repo_root).as_posix()
            if any(part in {".git", ".venv", "venv", "node_modules", "__pycache__", "doctor_local"} for part in path.parts):
                continue
            paths.append(rel)
            if len(paths) >= 120:
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

    def _fallback_action(self, review: ArchitectureReview, repo_root: Path) -> PatchAction:
        target = repo_root / "docs" / "self_evolution_status.md"
        existing = ""
        if target.exists() and target.is_file():
            existing = target.read_text(encoding="utf-8", errors="ignore")[:40000]

        top_backlog = review.backlog_items[:5] or review.recommendations[:5]
        backlog_lines = "\n".join(f"- {item}" for item in top_backlog) if top_backlog else "- No backlog items recorded."
        strengths = "\n".join(f"- {item}" for item in review.strengths[:5]) or "- No strengths recorded."
        weaknesses = "\n".join(f"- {item}" for item in review.weaknesses[:5]) or "- No weaknesses recorded."
        recommendations = "\n".join(f"- {item}" for item in review.recommendations[:5]) or "- No recommendations recorded."

        new_content = (
            "# Self-Evolution Status\n\n"
            "This file is maintained by the wake reviewer to ensure each successful wake cycle leaves a small, safe, auditable artifact.\n\n"
            f"## Reviewed At\n\n{review.reviewed_at}\n\n"
            f"## Risk Level\n\n{review.risk_level}\n\n"
            f"## Diagnosis\n\n{review.diagnosis}\n\n"
            "## Top Strengths\n\n"
            f"{strengths}\n\n"
            "## Top Weaknesses\n\n"
            f"{weaknesses}\n\n"
            "## Current Recommendations\n\n"
            f"{recommendations}\n\n"
            "## Backlog Focus\n\n"
            f"{backlog_lines}\n"
        )

        if existing.strip() == new_content.strip():
            new_content += "\n\n## Wake Cycle Note\n\n- Artifact refreshed with unchanged content to preserve auditable state.\n"

        return PatchAction(
            path="docs/self_evolution_status.md",
            operation="replace_file",
            description="Write a small safe self-evolution status artifact so each wake cycle produces an auditable low-risk improvement.",
            new_content=new_content,
            pattern=None,
            replacement=None,
        )

    def _ensure_actionable_review(self, review: ArchitectureReview, repo_root: Path) -> ArchitectureReview:
        if review.self_evolution_actions:
            return review

        review.self_evolution_actions = [self._fallback_action(review, repo_root)]
        review.execution_notes.append(
            "No bounded code change was returned by the model, so the reviewer generated a safe documentation artifact to keep self-evolution active and auditable."
        )
        if review.risk_level == "high":
            review.risk_level = "medium"
        return review

    def review(self, *, memory_snapshot: dict, repo_root: Path, recent_summary: str) -> ArchitectureReview:
        repo_tree = self._repo_tree(repo_root)
        key_file_context = self._key_file_context(repo_root)
        prompt = (
            f"Repo root: {repo_root}\n"
            f"Recent summary: {recent_summary or 'None'}\n"
            f"Maintenance command: {self.settings.maintenance_command}\n"
            f"Current command: {self.settings.command}\n"
            f"Repo tree: {json.dumps(repo_tree)[:40000]}\n"
            f"Key file context: {json.dumps(key_file_context)[:120000]}\n"
            f"Memory snapshot: {json.dumps(memory_snapshot)[:50000]}\n\n"
            "You must return at least one low-risk self_evolution_action when the repo is healthy. "
            "Prefer a markdown or documentation artifact if you are not confident editing runtime code."
        )
        data = self.client.generate_json(
            model=self.settings.openai_model_review,
            system=ARCHITECTURE_REVIEW_SYSTEM,
            prompt=prompt,
            schema=REVIEW_SCHEMA,
        )
        review = ArchitectureReview(**data)
        return self._ensure_actionable_review(review, repo_root)
