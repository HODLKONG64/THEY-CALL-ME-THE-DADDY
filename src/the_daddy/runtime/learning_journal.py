from __future__ import annotations

from typing import Any

from ..models import LearningJournalEntry


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _extract_blocked_targets(record) -> list[str]:
    targets: list[str] = []

    for event in getattr(record, "trace", []) or []:
        if not isinstance(event, dict):
            continue
        if event.get("event") != "patch_apply_failed":
            continue
        path = _normalize_text(event.get("path"))
        if path and path not in targets:
            targets.append(path)

    self_evolution = getattr(record, "self_evolution", None)
    reasons = getattr(self_evolution, "reasons", []) if self_evolution is not None else []
    for reason in reasons or []:
        text = _normalize_text(reason)
        if "->" not in text:
            continue
        _, right = text.rsplit("->", 1)
        for raw in right.split(","):
            path = _normalize_text(raw)
            if path and path not in targets:
                targets.append(path)

    return targets


def _extract_successful_targets(record) -> list[str]:
    targets: list[str] = []
    for patch in getattr(record, "patches_applied", []) or []:
        if isinstance(patch, dict):
            path = _normalize_text(patch.get("path"))
        else:
            path = _normalize_text(getattr(patch, "path", ""))
        if path and path not in targets:
            targets.append(path)
    return targets


def _confidence_for_record(record) -> str:
    if getattr(record, "success", False) and getattr(record, "patches_applied", []):
        return "high"
    if getattr(record, "success", False):
        return "medium"
    return "low"


def _outcome_for_record(record) -> str:
    if getattr(record, "success", False) and getattr(record, "patches_applied", []):
        return "success_patch"
    if getattr(record, "success", False):
        return "safe_noop"
    if getattr(record, "patches_applied", []):
        return "blocked_patch"
    return "verification_failure"


def _behavior_tags(review, record) -> list[str]:
    tags: list[str] = ["bounded_maintenance"]
    if getattr(record, "patches_applied", []):
        tags.append("patch_applied")
    else:
        tags.append("safe_noop")

    notes = [str(note) for note in getattr(review, "execution_notes", []) or []]
    lowered = " | ".join(notes).lower()

    if "blocked retry" in lowered:
        tags.append("anti_repeat")
    if "replace_file on existing runtime helper" in lowered:
        tags.append("protected_helper")
    if "regex_replace action whose pattern does not match" in lowered:
        tags.append("regex_anchor_guard")
    if "documentation/observability backlog churn" in lowered:
        tags.append("noop_over_doc_churn")

    return tags


def _subsystem_for_record(record) -> str:
    targets = _extract_successful_targets(record) or _extract_blocked_targets(record)
    if not targets:
        return "general"
    target_text = " | ".join(targets).lower()
    if "runtime/" in target_text:
        return "runtime"
    if "memory/" in target_text:
        return "memory"
    if "agents/" in target_text:
        return "agents"
    return "general"


def _lessons(review, record) -> list[str]:
    lessons: list[str] = [
        "Learn safely before acting boldly.",
        "Prefer no-op over damage when confidence is weak.",
    ]

    if getattr(record, "patches_applied", []):
        lessons.append("Small bounded patches that pass tests can be promoted safely.")
    else:
        lessons.append("When no executable safe patch exists, record the lesson and stand down.")

    blocked_targets = _extract_blocked_targets(record)
    if blocked_targets:
        lessons.append("Repeated blocked targets should cool down before being proposed again.")

    notes = [str(note) for note in getattr(review, "execution_notes", []) or []]
    lowered = " | ".join(notes).lower()
    if "documentation/observability backlog churn" in lowered:
        lessons.append("Documentation churn is not a substitute for a valid code improvement.")
    if "replace_file on existing runtime helper" in lowered:
        lessons.append("Existing runtime helpers require stronger proof and should not be bluntly replaced.")

    seen: set[str] = set()
    unique: list[str] = []
    for item in lessons:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def build_learning_journal_entry(*, run_id: str, review, record) -> LearningJournalEntry:
    successful_targets = _extract_successful_targets(record)
    blocked_targets = _extract_blocked_targets(record)
    failed_targets: list[str] = []
    if not getattr(record, "success", False):
        failed_targets = blocked_targets[:]

    return LearningJournalEntry(
        run_id=run_id,
        role_mode="bounded_maintenance",
        confidence=_confidence_for_record(record),
        outcome=_outcome_for_record(record),
        subsystem=_subsystem_for_record(record),
        lessons=_lessons(review, record),
        blocked_targets=blocked_targets,
        successful_targets=successful_targets,
        failed_targets=failed_targets,
        behavior_tags=_behavior_tags(review, record),
    )
