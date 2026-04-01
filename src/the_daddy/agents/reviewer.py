from __future__ import annotations

import json
from pathlib import Path

from ..config import Settings
from ..models import ArchitectureReview
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
            f"Memory snapshot: {json.dumps(memory_snapshot)[:50000]}"
        )
        data = self.client.generate_json(
            model=self.settings.openai_model_review,
            system=ARCHITECTURE_REVIEW_SYSTEM,
            prompt=prompt,
            schema=REVIEW_SCHEMA,
        )
        return ArchitectureReview.model_validate(data)
