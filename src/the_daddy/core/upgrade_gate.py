from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class UpgradeGateError(RuntimeError):
    """Raised when OpenAI upgrade advice is missing, stale, invalid, or rejects proceeding."""


REQUIRED_ADVICE_FIELDS = [
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
]


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _resolve_max_age_hours() -> int:
    raw = os.environ.get("DADDY_UPGRADE_ADVICE_MAX_AGE_HOURS", "6").strip()
    try:
        return max(1, int(raw))
    except ValueError as exc:
        raise UpgradeGateError(
            f"DADDY_UPGRADE_ADVICE_MAX_AGE_HOURS must be an integer, got {raw!r}"
        ) from exc


def _resolve_advice_path(explicit_path: str | Path | None = None) -> Path:
    if explicit_path is not None and str(explicit_path).strip():
        return Path(str(explicit_path)).expanduser().resolve()

    raw = os.environ.get("DADDY_UPGRADE_ADVICE_PATH", "").strip()
    if not raw:
        raise UpgradeGateError(
            "DADDY_UPGRADE_ADVICE_PATH is required before self-evolution or patching can proceed."
        )
    return Path(raw).expanduser().resolve()


def load_upgrade_advice(advice_path: str | Path | None = None) -> dict[str, Any]:
    resolved = _resolve_advice_path(advice_path)
    if not resolved.exists():
        raise UpgradeGateError(f"OpenAI upgrade advice file is missing: {resolved}")

    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise UpgradeGateError(f"OpenAI upgrade advice file is not valid JSON: {resolved}") from exc

    if not isinstance(payload, dict):
        raise UpgradeGateError("OpenAI upgrade advice payload must be a JSON object")

    missing = [key for key in REQUIRED_ADVICE_FIELDS if key not in payload]
    if missing:
        raise UpgradeGateError(
            f"OpenAI upgrade advice is missing required fields: {', '.join(missing)}"
        )

    return payload


def validate_upgrade_advice(
    advice_path: str | Path | None = None,
    *,
    max_age_hours: int | None = None,
    require_approval: bool = True,
) -> dict[str, Any]:
    advice = load_upgrade_advice(advice_path)

    age_limit = max_age_hours if max_age_hours is not None else _resolve_max_age_hours()
    generated_at = _parse_iso(str(advice["generated_at"]))
    oldest_allowed = datetime.now(timezone.utc) - timedelta(hours=age_limit)
    if generated_at < oldest_allowed:
        raise UpgradeGateError(
            f"OpenAI upgrade advice is stale: {generated_at.isoformat()} older than {age_limit}h"
        )

    if not isinstance(advice["allow_proceed"], bool):
        raise UpgradeGateError("OpenAI upgrade advice field 'allow_proceed' must be a boolean")

    target_files = advice.get("target_files")
    if not isinstance(target_files, list) or not target_files:
        raise UpgradeGateError(
            "OpenAI upgrade advice must contain at least one target file"
        )

    if require_approval and not advice["allow_proceed"]:
        raise UpgradeGateError(
            "OpenAI upgrade advice did not approve proceeding: "
            + str(advice.get("summary", "no summary provided"))
        )

    return advice


def validate_upgrade_gate_for_settings(settings: Any) -> dict[str, Any]:
    self_evolution_enabled = bool(getattr(settings, "enable_self_evolution", True))
    architecture_enabled = bool(getattr(settings, "enable_architecture_lane", True))

    if not self_evolution_enabled and not architecture_enabled:
        return {
            "allow_proceed": True,
            "summary": "Upgrade gate bypassed because self-evolution and architecture lane are disabled.",
            "repo_state": "gate_bypassed",
            "problem_type": "healthy_meaningful_progress",
            "recommended_next_step": "none",
            "target_files": ["gate_bypassed"],
            "forbidden_repeat_patterns": [],
            "required_constraints": [],
            "tests_to_run": [],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    return validate_upgrade_advice()
