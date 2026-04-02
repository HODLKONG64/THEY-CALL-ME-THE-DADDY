from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openai import OpenAI

from ..config import Settings
from ..models import ArchitectureReview, SelfEvolutionAction


class WakeReviewer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key)

    def _repo_snapshot(self, repo_root: Path) -> dict[str, Any]:
        tracked: list[str] = []
        for path in sorted(repo_root.rglob("*")):
            if not path.is_file():
                continue
            rel = str(path.relative_to(repo_root))
            if any(part in {".git", ".venv", "__pycache__", "doctor_local", ".pytest_cache"} for part in path.parts):
                continue
            tracked.append(rel)
            if len(tracked) >= 120:
                break

        key_files: dict[str, str] = {}
        for rel in [
            "README.md",
            "ARCHITECTURE.md",
            ".github/workflows/daddy-cycle.yml",
            "src/the_daddy/engine.py",
            "src/the_daddy/policy.py",
            "src/the_daddy/models.py",
            "src/the_daddy/memory/repository.py",
        ]:
            p = repo_root / rel
            if p.exists() and p.is_file():
                key_files[rel] = p.read_text(encoding="utf-8", errors="ignore")[:12000]

        return {"tracked_files": tracked, "key_files": key_files}

    def review(self, memory_snapshot: dict[str, Any], repo_root: Path, recent_summary: str = "") -> ArchitectureReview:
        snapshot = self._repo_snapshot(repo_root)
        schema = {
            "type": "object",
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
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "risk": {"type": "string", "enum": ["safe", "branch", "recommend"]},
                            "patches": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "path": {"type": "string"},
                                        "operation": {"type": "string", "enum": ["replace_file", "regex_replace"]},
                                        "new_content": {"type": ["string", "null"]},
                                        "pattern": {"type": ["string", "null"]},
                                        "replacement": {"type": ["string", "null"]},
                                        "description": {"type": "string"},
                                    },
                                    "required": ["path", "operation", "new_content", "pattern", "replacement", "description"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["title", "description", "risk", "patches"],
                        "additionalProperties": False,
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
            "additionalProperties": False,
        }

        prompt = (
            "You are the wake reviewer for a bounded self-evolving repo maintenance system. "
            "You must review the actual repo snapshot and always return at least one safe self_evolution_action. "
            "Safe actions must only touch docs, architecture notes, tests, or additive metadata guards. "
            "Do not touch secrets, dependency lists, destructive commands, or broad rewrites. "
            "Return structured JSON only."
        )

        user_content = {
            "recent_summary": recent_summary,
            "memory_snapshot": memory_snapshot,
            "repo_snapshot": snapshot,
            "required_behavior": [
                "Always produce at least one self_evolution_action.",
                "At least one action must be safe and auto-applicable.",
                "Prefer documentation, tests, schema guards, provenance notes, rollback metadata, or metrics ledger scaffolding.",
                "Do not propose empty action arrays.",
            ],
        }

        response = self.client.responses.create(
            model=self.settings.openai_model_review,
            input=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(user_content)},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "wake_review",
                    "schema": schema,
                    "strict": True,
                }
            },
        )
        payload = json.loads(response.output_text)
        actions = [SelfEvolutionAction.model_validate(item) for item in payload.pop("self_evolution_actions")]
        return ArchitectureReview.model_validate({**payload, "self_evolution_actions": actions})
