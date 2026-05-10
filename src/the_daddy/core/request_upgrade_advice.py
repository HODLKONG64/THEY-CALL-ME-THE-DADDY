from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ..models import MemoryState
from ..runtime.redaction import sanitize_list, sanitize_mapping, sanitize_text


SYSTEM_PROMPT = """You are auditing a bounded self-maintaining repository agent.
Your job is to decide whether the workflow should proceed with an upgrade cycle right now.

You must be strict.
Do not approve filler work.
Do not approve repeated keep-alive patches unless there is no other safe option.
If the repository appears to be stuck in a safe-loop, say so clearly and recommend concrete upgrade targets.

Return JSON only.
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_repo_snapshot(repo_root: Path) -> dict[str, Any]:
    tracked_files: list[str] = []
    preview_files: list[dict[str, str]] = []
    ignored_parts = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "build", "dist"}

    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in ignored_parts for part in path.parts):
            continue

        rel = str(path.relative_to(repo_root))
        tracked_files.append(rel)

        if len(preview_files) < 25 and path.suffix in {".py", ".json", ".toml", ".md", ".yml", ".yaml"}:
            try:
                preview_files.append(
                    {
                        "path": rel,
                        "content_preview": path.read_text(encoding="utf-8", errors="ignore")[:8000],
                    }
                )
            except Exception:
                continue

        if len(tracked_files) >= 250:
            break

    return {
        "tracked_files": tracked_files,
        "preview_files": preview_files,
    }


def build_learning_summary(repo_root: Path) -> dict[str, Any]:
    memory_name = os.environ.get("DADDY_MEMORY_FILE", "sam-memory.json").strip() or "sam-memory.json"
    local_state_dir = os.environ.get("DADDY_LOCAL_STATE_DIR", "doctor_local").strip() or "doctor_local"
    memory_path = (repo_root / local_state_dir / memory_name).resolve()
    if not memory_path.exists():
        return {
            "recent_outcomes": [],
            "recurring_blockers": [],
            "repeated_files": [],
            "subsystems": [],
            "avoid_next_time": [],
            "successful_patterns": [],
            "advice_actionability": {
                "total": 0,
                "advice_actionable_count": 0,
                "patch_attempted_count": 0,
                "verified_progress_count": 0,
                "clean_no_action_count": 0,
                "blocked_or_failed_count": 0,
                "advice_not_actionable_count": 0,
                "fake_noop_blocked_count": 0,
            },
        }
    try:
        payload = json.loads(memory_path.read_text(encoding="utf-8"))
        state = MemoryState.model_validate(payload)
    except Exception:
        return {
            "recent_outcomes": [],
            "recurring_blockers": [],
            "repeated_files": [],
            "subsystems": [],
            "avoid_next_time": [],
            "successful_patterns": [],
            "advice_actionability": {
                "total": 0,
                "advice_actionable_count": 0,
                "patch_attempted_count": 0,
                "verified_progress_count": 0,
                "clean_no_action_count": 0,
                "blocked_or_failed_count": 0,
                "advice_not_actionable_count": 0,
                "fake_noop_blocked_count": 0,
            },
        }

    items = list(state.run_learning_ledger or [])[-10:]
    outcomes = [str(i.outcome) for i in items][-5:]
    blockers: dict[str, int] = {}
    files: dict[str, int] = {}
    subsystems: list[str] = []
    avoid: list[str] = []
    success: list[str] = []
    for item in items:
        if item.blocked_reason:
            cleaned_reason = sanitize_text(item.blocked_reason)
            blockers[cleaned_reason] = blockers.get(cleaned_reason, 0) + 1
        for path in item.files_involved:
            files[path] = files.get(path, 0) + 1
        if item.subsystem:
            subsystems.append(item.subsystem)
        for lesson in item.avoid_next_time:
            cleaned_lesson = sanitize_text(lesson)
            if cleaned_lesson and cleaned_lesson not in avoid:
                avoid.append(cleaned_lesson)
        if item.outcome == "success_with_patch":
            for pattern in item.what_worked:
                cleaned_pattern = sanitize_text(pattern)
                if cleaned_pattern and cleaned_pattern not in success:
                    success.append(cleaned_pattern)

    total = len(items)
    advice_actionable_count = sum(1 for i in items if i.outcome in {"success_with_patch", "clean_no_action"})
    patch_attempted_count = sum(1 for i in items if int(getattr(i, "attempted_patch_count", 0) or 0) > 0)
    verified_progress_count = sum(1 for i in items if i.outcome == "success_with_patch")
    clean_no_action_count = sum(1 for i in items if i.outcome == "clean_no_action")
    blocked_or_failed_count = sum(
        1
        for i in items
        if i.outcome
        in {
            "verification_failed",
            "attempted_patch_failed",
            "policy_rejected",
            "git_pr_lane_failed",
            "blocked_fake_noop",
        }
    )
    advice_not_actionable_count = sum(1 for i in items if i.outcome == "advice_not_actionable")
    fake_noop_blocked_count = sum(1 for i in items if i.outcome == "blocked_fake_noop")

    return sanitize_mapping({
        "recent_outcomes": outcomes,
        "recurring_blockers": [
            {"blocked_reason": sanitize_text(reason), "count": count}
            for reason, count in sorted(blockers.items(), key=lambda x: (-x[1], x[0]))[:5]
        ],
        "repeated_files": [
            {"path": sanitize_text(path), "count": count}
            for path, count in sorted(files.items(), key=lambda x: (-x[1], x[0]))[:5]
        ],
        "subsystems": sanitize_list(subsystems[-10:]),
        "avoid_next_time": sanitize_list(avoid[:10]),
        "successful_patterns": sanitize_list(success[:10]),
        "advice_actionability": {
            "total": total,
            "advice_actionable_count": advice_actionable_count,
            "patch_attempted_count": patch_attempted_count,
            "verified_progress_count": verified_progress_count,
            "clean_no_action_count": clean_no_action_count,
            "blocked_or_failed_count": blocked_or_failed_count,
            "advice_not_actionable_count": advice_not_actionable_count,
            "fake_noop_blocked_count": fake_noop_blocked_count,
        },
    })


def advice_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "allow_proceed": {"type": "boolean"},
            "summary": {"type": "string"},
            "repo_state": {"type": "string"},
            "problem_type": {
                "type": "string",
                "enum": [
                    "healthy_meaningful_progress",
                    "healthy_safe_loop",
                    "failing_repo",
                    "insufficient_context",
                ],
            },
            "recommended_next_step": {"type": "string"},
            "target_files": {
                "type": "array",
                "items": {"type": "string"},
            },
            "forbidden_repeat_patterns": {
                "type": "array",
                "items": {"type": "string"},
            },
            "required_constraints": {
                "type": "array",
                "items": {"type": "string"},
            },
            "tests_to_run": {
                "type": "array",
                "items": {"type": "string"},
            },
            "generated_at": {"type": "string"},
        },
        "required": [
            "allow_proceed",
            "summary",
            "repo_state",
            "problem_type",
            "recommended_next_step",
            "target_files",
            "forbidden_repeat_patterns",
            "required_constraints",
            "tests_to_run",
            "generated_at",
        ],
    }


def extract_output_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"]

    parts: list[str] = []
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            text_value = content.get("text")
            if isinstance(text_value, str):
                parts.append(text_value)
            elif isinstance(text_value, dict) and isinstance(text_value.get("value"), str):
                parts.append(text_value["value"])
    return "\n".join(parts).strip()


def request_upgrade_advice(repo_root: Path, model: str) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required")

    snapshot = build_repo_snapshot(repo_root)
    learning_summary = build_learning_summary(repo_root)
    user_prompt = json.dumps(
        {
            "instruction": "Audit this repository snapshot and decide whether the upgrade workflow should proceed. If it is in a safe-loop, explicitly identify that and recommend the best bounded upgrade targets.",
            "repo_snapshot": snapshot,
            "run_learning_summary": learning_summary,
            "current_goal": "Do not let the workflow move forward until OpenAI provides explicit upgrade advice.",
        },
        indent=2,
    )

    payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_prompt}],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "upgrade_advice",
                "strict": True,
                "schema": advice_schema(),
            }
        },
    }

    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    text = extract_output_text(data)
    if not text:
        raise RuntimeError("OpenAI returned no advice text")

    advice = json.loads(text)
    advice["generated_at"] = utc_now_iso()
    return advice


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default=os.environ.get("OPENAI_UPGRADE_MODEL", "gpt-5.4"))
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    advice = request_upgrade_advice(repo_root=repo_root, model=args.model)
    output_path.write_text(json.dumps(advice, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(advice, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
