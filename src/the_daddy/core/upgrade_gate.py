from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class UpgradeGateError(RuntimeError):
    pass


REQUIRED_FIELDS = [
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
        raise UpgradeGateError(f"Upgrade advice file does not exist: {resolved}")

    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except Exception as exc:
        raise UpgradeGateError(f"Upgrade advice file is unreadable or invalid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise UpgradeGateError("Upgrade advice payload must be a JSON object.")
    return payload


def validate_upgrade_advice(
    advice_path: str | Path | None = None,
    *,
    require_approval: bool = True,
    max_age_hours: int = 6,
) -> dict[str, Any]:
    advice = load_upgrade_advice(advice_path)

    missing = [key for key in REQUIRED_FIELDS if key not in advice]
    if missing:
        raise UpgradeGateError(f"Upgrade advice is missing required fields: {', '.join(missing)}")

    if not isinstance(advice["allow_proceed"], bool):
        raise UpgradeGateError("allow_proceed must be a boolean")

    generated_at = _parse_iso(str(advice["generated_at"]))
    if generated_at < datetime.now(timezone.utc) - timedelta(hours=max_age_hours):
        raise UpgradeGateError("Upgrade advice is stale")

    if not isinstance(advice.get("target_files"), list) or not advice["target_files"]:
        raise UpgradeGateError("Upgrade advice must include at least one target file")

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
            "repair_mode": False,
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

    advice = validate_upgrade_advice(require_approval=False)
    if advice["allow_proceed"]:
        advice["repair_mode"] = False
        return advice

    problem_type = str(advice.get("problem_type", "")).strip().lower()
    if problem_type in {"healthy_safe_loop", "healthy_meaningful_progress"}:
        advice["repair_mode"] = True
        return advice

    raise UpgradeGateError(
        "OpenAI upgrade advice did not approve proceeding: "
        + str(advice.get("summary", "no summary provided"))
    )
