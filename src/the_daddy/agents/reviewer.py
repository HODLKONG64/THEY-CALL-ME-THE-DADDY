from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..config import Settings
from ..models import (
    ArchitecturePlan,
    ArchitectureReview,
    PatchAction,
    PlannedWorkItem,
    SelfEvolutionAction,
)
from .openai_client import OpenAIJSONClient


BANNED_TEST_PATH_PATTERNS = {
    "tests/test_wake_review_invariant.py",
    "tests/test_wake_review_invariants.py",
    "tests/test_wake_review_output.py",
    "tests/test_wake_review_contract.py",
    "tests/test_self_evolution.py",
}

BANNED_TEST_TITLE_PATTERNS = (
    "wake-review invariant",
    "wake review invariant",
    "wake-review output",
    "wake review output",
    "wake-review contract",
    "wake review contract",
    "self-evolution action existence",
    "self evolution action existence",
    "safe self-evolution action existence",
)

PROACTIVE_RUNTIME_PATH = "src/the_daddy/runtime/trace_summary.py"
FALLBACK_RUNTIME_PATH = "src/the_daddy/runtime/reviewer_fallback.py"
ARCHITECTURE_RUNTIME_PATH = "src/the_daddy/runtime/architecture_probe.py"
ERROR_DIGEST_RUNTIME_PATH = "src/the_daddy/runtime/error_digest.py"
RUN_HEALTH_RUNTIME_PATH = "src/the_daddy/runtime/run_health.py"

BANNED_SELF_EVOLUTION_PATHS = {
    "src/the_daddy/runtime/command_runner.py",
}

SAFE_NEW_FILE_ALLOWLIST = {
    PROACTIVE_RUNTIME_PATH,
    FALLBACK_RUNTIME_PATH,
    ARCHITECTURE_RUNTIME_PATH,
    ERROR_DIGEST_RUNTIME_PATH,
    RUN_HEALTH_RUNTIME_PATH,
}

ALLOWLISTED_RUNTIME_HELPERS = {
    PROACTIVE_RUNTIME_PATH,
    FALLBACK_RUNTIME_PATH,
    ARCHITECTURE_RUNTIME_PATH,
    ERROR_DIGEST_RUNTIME_PATH,
    RUN_HEALTH_RUNTIME_PATH,
}

BANNED_INVENTED_MODULE_FILENAMES = {
    "logging_utils.py",
    "reviewer.py",
    "helper.py",
    "helpers.py",
    "utils.py",
    "utility.py",
    "diagnostics.py",
    "observability.py",
    "telemetry.py",
    "logger.py",
    "logging.py",
}

HELPER_SLOT_CAPS = {
    PROACTIVE_RUNTIME_PATH: 8,
    ERROR_DIGEST_RUNTIME_PATH: 6,
    RUN_HEALTH_RUNTIME_PATH: 6,
    FALLBACK_RUNTIME_PATH: 5,
    ARCHITECTURE_RUNTIME_PATH: 5,
}

HELPER_GROWTH_REGISTRY: dict[str, list[dict[str, str]]] = {
    PROACTIVE_RUNTIME_PATH: [
        {
            "function_name": "summarize_self_evolution_skips",
            "title": "Append normalized self-evolution trace helper",
            "description": "Append a bounded helper function to the existing trace summary runtime helper using regex_replace.",
            "function_block": """

def summarize_self_evolution_skips(reasons: list[str] | None = None) -> dict[str, Any]:
    items = [str(item).strip() for item in (reasons or []) if str(item).strip()]
    blocked = [item for item in items if item.lower().startswith("blocked ")]
    return {
        "total_reasons": len(items),
        "blocked_count": len(blocked),
        "blocked_reasons": blocked,
        "all_reasons": items,
    }
""",
        },
        {
            "function_name": "summarize_build_action_titles",
            "title": "Append compact build-action summary helper",
            "description": "Append a bounded helper that summarizes build-action titles on the existing trace summary runtime helper using regex_replace.",
            "function_block": """

def summarize_build_action_titles(actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = actions or []
    titles = [str(item.get("title", "")).strip() for item in items if str(item.get("title", "")).strip()]
    return {
        "count": len(titles),
        "titles": titles[:10],
        "first_title": titles[0] if titles else "",
    }
""",
        },
        {
            "function_name": "summarize_build_pressure_paths",
            "title": "Append build-pressure path summary helper",
            "description": "Append a bounded helper that summarizes build-pressure related files on the existing trace summary runtime helper using regex_replace.",
            "function_block": """

def summarize_build_pressure_paths(actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = actions or []
    paths: dict[str, int] = {}

    for item in items:
        for path in item.get("related_files", []) or []:
            path_text = str(path).strip()
            if not path_text:
                continue
            paths[path_text] = paths.get(path_text, 0) + 1

    ranked = sorted(paths.items(), key=lambda item: (-item[1], item[0]))
    return {
        "path_count": len(paths),
        "top_paths": ranked[:10],
        "first_path": ranked[0][0] if ranked else "",
    }
""",
        },
        {
            "function_name": "summarize_helper_lane_status",
            "title": "Append helper-lane saturation summary helper",
            "description": "Append a bounded helper that summarizes helper-lane saturation and build pressure on the existing trace summary runtime helper using regex_replace.",
            "function_block": """

def summarize_helper_lane_status(actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = actions or []
    unique_titles: list[str] = []
    helper_paths: list[str] = []
    helper_counts: dict[str, int] = {}

    for item in items:
        title = str(item.get("title", "")).strip()
        if title and title not in unique_titles:
            unique_titles.append(title)

        for path in item.get("related_files", []) or []:
            path_text = str(path).strip()
            if not path_text:
                continue
            helper_counts[path_text] = helper_counts.get(path_text, 0) + 1
            if path_text not in helper_paths:
                helper_paths.append(path_text)

    ranked = sorted(helper_counts.items(), key=lambda item: (-item[1], item[0]))
    return {
        "title_count": len(unique_titles),
        "helper_path_count": len(helper_paths),
        "top_helper_paths": ranked[:10],
        "first_helper_path": ranked[0][0] if ranked else "",
        "active": bool(unique_titles) or bool(helper_paths),
    }
""",
        },
        {
            "function_name": "summarize_recent_pressure_persistence",
            "title": "Append recent-pressure persistence helper",
            "description": "Append a bounded helper that tracks whether recent build pressure keeps pointing at the same files on the existing trace summary runtime helper using regex_replace.",
            "function_block": """

def summarize_recent_pressure_persistence(actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = actions or []
    related_files: list[str] = []

    for item in items:
        for path in item.get("related_files", []) or []:
            path_text = str(path).strip()
            if path_text and path_text not in related_files:
                related_files.append(path_text)

    return {
        "related_file_count": len(related_files),
        "related_files": related_files[:10],
        "active": bool(related_files),
    }
""",
        },
        {
            "function_name": "summarize_planning_hint_state",
            "title": "Append stable planning-hint helper",
            "description": "Append a bounded helper that summarizes whether trace-level planning hints are present and stable on the existing trace summary runtime helper using regex_replace.",
            "function_block": """

def summarize_planning_hint_state(actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = actions or []
    titles = [str(item.get("title", "")).strip() for item in items if str(item.get("title", "")).strip()]
    notes: list[str] = []

    for item in items:
        for note in item.get("notes", []) or []:
            note_text = str(note).strip()
            if note_text:
                notes.append(note_text)

    unique_notes = list(dict.fromkeys(notes))
    return {
        "title_count": len(titles),
        "note_count": len(unique_notes),
        "first_title": titles[0] if titles else "",
        "first_note": unique_notes[0] if unique_notes else "",
        "active": bool(titles) or bool(unique_notes),
    }
""",
        },
    ],
    ERROR_DIGEST_RUNTIME_PATH: [
        {
            "function_name": "summarize_traceback_excerpt",
            "title": "Append traceback extraction helper to error_digest",
            "description": "Append a bounded traceback excerpt helper to the existing error digest runtime helper using regex_replace.",
            "function_block": """

def summarize_traceback_excerpt(text: str, max_lines: int = 12) -> dict[str, Any]:
    lines = [line.rstrip() for line in str(text or "").splitlines() if line.strip()]
    tail = lines[-max_lines:]
    return {
        "line_count": len(lines),
        "excerpt": tail,
        "last_line": tail[-1] if tail else "",
    }
""",
        },
        {
            "function_name": "summarize_error_paths",
            "title": "Append error-path summary helper to error_digest",
            "description": "Append a bounded helper that summarizes recurring error paths on the existing error digest runtime helper using regex_replace.",
            "function_block": """

def summarize_error_paths(events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = events or []
    paths: dict[str, int] = {}

    for item in items:
        path = str(item.get("path", "")).strip()
        if not path:
            continue
        paths[path] = paths.get(path, 0) + 1

    ranked = sorted(paths.items(), key=lambda item: (-item[1], item[0]))
    return {
        "path_count": len(paths),
        "top_paths": ranked[:10],
        "first_path": ranked[0][0] if ranked else "",
    }
""",
        },
        {
            "function_name": "summarize_error_messages",
            "title": "Append error-message summary helper to error_digest",
            "description": "Append a bounded helper that summarizes recurring error messages on the existing error digest runtime helper using regex_replace.",
            "function_block": """

def summarize_error_messages(events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = events or []
    counts: dict[str, int] = {}

    for item in items:
        message = str(item.get("error", "")).strip()
        if not message:
            continue
        counts[message] = counts.get(message, 0) + 1

    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return {
        "message_count": len(counts),
        "top_messages": ranked[:10],
        "first_message": ranked[0][0] if ranked else "",
    }
""",
        },
        {
            "function_name": "summarize_error_event_kinds",
            "title": "Append error-event kind summary helper to error_digest",
            "description": "Append a bounded helper that summarizes recurring error event kinds on the existing error digest runtime helper using regex_replace.",
            "function_block": """

def summarize_error_event_kinds(events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = events or []
    counts: dict[str, int] = {}

    for item in items:
        event = str(item.get("event", "")).strip()
        if not event:
            continue
        counts[event] = counts.get(event, 0) + 1

    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return {
        "kind_count": len(counts),
        "top_kinds": ranked[:10],
        "first_kind": ranked[0][0] if ranked else "",
    }
""",
        },
    ],
    RUN_HEALTH_RUNTIME_PATH: [
        {
            "function_name": "summarize_run_velocity",
            "title": "Append runtime run-velocity helper",
            "description": "Append a bounded run-velocity helper to the existing run health runtime helper using regex_replace.",
            "function_block": """

def summarize_run_velocity(
    runs: list[dict[str, Any]] | None = None,
    window: int = RECENT_VELOCITY_WINDOW,
) -> dict[str, Any]:
    items = runs or []
    effective_window = max(1, int(window))
    sample = items[-effective_window:] if items else []

    success_count = sum(1 for item in sample if bool(item.get("success", False)))
    failure_count = len(sample) - success_count

    return {
        "sample_size": len(sample),
        "window": effective_window,
        "successes": success_count,
        "failures": failure_count,
    }
""",
        },
        {
            "function_name": "summarize_mode_distribution",
            "title": "Append runtime mode-distribution helper",
            "description": "Append a bounded mode-distribution helper to the existing run health runtime helper using regex_replace.",
            "function_block": """

def summarize_mode_distribution(
    runs: list[dict[str, Any]] | None = None,
    window: int = 20,
) -> dict[str, Any]:
    items = runs or []
    effective_window = max(1, int(window))
    sample = items[-effective_window:] if items else []
    counts: dict[str, int] = {}

    for item in sample:
        mode = str(item.get("selected_mode", "unknown")).strip() or "unknown"
        counts[mode] = counts.get(mode, 0) + 1

    return {
        "sample_size": len(sample),
        "window": effective_window,
        "mode_counts": counts,
        "distinct_modes": len(counts),
    }
""",
        },
        {
            "function_name": "summarize_patchless_streak",
            "title": "Append runtime patchless-streak helper",
            "description": "Append a bounded helper that summarizes consecutive patchless runs on the existing run health runtime helper using regex_replace.",
            "function_block": """

def summarize_patchless_streak(runs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = runs or []
    streak = 0

    for item in reversed(items):
        patch_count = int(item.get("patch_count", 0) or 0)
        if patch_count > 0:
            break
        streak += 1

    latest_mode = ""
    if items:
        latest_mode = str(items[-1].get("selected_mode", "")).strip()

    return {
        "patchless_streak": streak,
        "total_runs": len(items),
        "latest_mode": latest_mode,
        "active": streak > 0,
    }
""",
        },
        {
            "function_name": "summarize_recent_patch_mix",
            "title": "Append recent patch-mix helper",
            "description": "Append a bounded helper that summarizes patched versus patchless runs on the existing run health runtime helper using regex_replace.",
            "function_block": """

def summarize_recent_patch_mix(
    runs: list[dict[str, Any]] | None = None,
    window: int = 10,
) -> dict[str, Any]:
    items = (runs or [])[-max(1, int(window)):]
    patch_counts = [int(item.get("patch_count", 0) or 0) for item in items]

    return {
        "sample_size": len(items),
        "patched_runs": sum(1 for count in patch_counts if count > 0),
        "patchless_runs": sum(1 for count in patch_counts if count == 0),
        "total_patches": sum(patch_counts),
    }
""",
        },
    ],
    FALLBACK_RUNTIME_PATH: [
        {
            "function_name": "fallback_review_summary",
            "title": "Append safe reviewer fallback summary helper",
            "description": "Append a bounded fallback summary helper without replacing the existing runtime helper file.",
            "function_block": """

def fallback_review_summary(reason: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(details or {})
    payload["reason"] = reason
    payload["source"] = "wake_reviewer_fallback"
    return payload
""",
        },
        {
            "function_name": "summarize_fallback_reason_counts",
            "title": "Append fallback reason-count helper",
            "description": "Append a bounded helper that summarizes fallback reason counts on the existing fallback runtime helper using regex_replace.",
            "function_block": """

def summarize_fallback_reason_counts(reasons: list[str] | None = None) -> dict[str, Any]:
    items = [str(item).strip() for item in (reasons or []) if str(item).strip()]
    counts: dict[str, int] = {}

    for item in items:
        counts[item] = counts.get(item, 0) + 1

    return {
        "reason_count": len(items),
        "unique_reasons": len(counts),
        "counts": counts,
    }
""",
        },
        {
            "function_name": "summarize_fallback_lane_status",
            "title": "Append fallback lane-status helper",
            "description": "Append a bounded helper that summarizes fallback-lane pressure and helper targets on the existing fallback runtime helper using regex_replace.",
            "function_block": """

def summarize_fallback_lane_status(
    reasons: list[str] | None = None,
    build_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    items = [str(item).strip() for item in (reasons or []) if str(item).strip()]
    actions = build_actions or []
    titles = [str(item.get("title", "")).strip() for item in actions if str(item.get("title", "")).strip()]
    helper_paths: list[str] = []

    for item in actions:
        for path in item.get("related_files", []) or []:
            path_text = str(path).strip()
            if path_text and path_text not in helper_paths:
                helper_paths.append(path_text)

    return {
        "reason_count": len(items),
        "build_action_count": len(titles),
        "first_build_action": titles[0] if titles else "",
        "helper_targets": helper_paths[:10],
        "has_pressure": bool(titles) or bool(helper_paths),
    }
""",
        },
        {
            "function_name": "summarize_fallback_pressure_targets",
            "title": "Append fallback pressure-target helper",
            "description": "Append a bounded helper that summarizes fallback pressure targets on the existing fallback runtime helper using regex_replace.",
            "function_block": """

def summarize_fallback_pressure_targets(build_actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = build_actions or []
    targets: list[str] = []

    for item in items:
        for path in item.get("related_files", []) or []:
            path_text = str(path).strip()
            if path_text and path_text not in targets:
                targets.append(path_text)

    return {
        "target_count": len(targets),
        "targets": targets[:10],
        "first_target": targets[0] if targets else "",
    }
""",
        },
    ],
    ARCHITECTURE_RUNTIME_PATH: [
        {
            "function_name": "architecture_probe_summary",
            "title": "Append architecture probe summary helper",
            "description": "Append a bounded architecture probe helper to the existing architecture runtime helper using regex_replace.",
            "function_block": """

def architecture_probe_summary(summary: str, files_touched: list[str] | None = None) -> dict[str, Any]:
    return {
        "summary": summary,
        "files_touched": files_touched or [],
        "source": "architecture_probe",
    }
""",
        },
        {
            "function_name": "summarize_architecture_targets",
            "title": "Append architecture target summary helper",
            "description": "Append a bounded helper that summarizes architecture target files on the existing architecture runtime helper using regex_replace.",
            "function_block": """

def summarize_architecture_targets(files_touched: list[str] | None = None) -> dict[str, Any]:
    items = [str(item).strip() for item in (files_touched or []) if str(item).strip()]
    return {
        "target_count": len(items),
        "targets": items,
        "first_target": items[0] if items else "",
    }
""",
        },
        {
            "function_name": "summarize_patch_bundle_paths",
            "title": "Append architecture patch-bundle summary helper",
            "description": "Append a bounded helper that summarizes architecture patch-bundle target paths on the existing architecture runtime helper using regex_replace.",
            "function_block": """

def summarize_patch_bundle_paths(patch_bundle: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = patch_bundle or []
    paths: list[str] = []

    for item in items:
        path_text = str(item.get("path", "")).strip()
        if path_text and path_text not in paths:
            paths.append(path_text)

    return {
        "patch_count": len(items),
        "path_count": len(paths),
        "paths": paths[:10],
        "first_path": paths[0] if paths else "",
    }
""",
        },
        {
            "function_name": "summarize_architecture_bundle_density",
            "title": "Append architecture bundle-density helper",
            "description": "Append a bounded helper that summarizes architecture bundle density on the existing architecture runtime helper using regex_replace.",
            "function_block": """

def summarize_architecture_bundle_density(patch_bundle: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = patch_bundle or []
    return {
        "patch_count": len(items),
        "paths": [str(item.get("path", "")).strip() for item in items if str(item.get("path", "")).strip()][:10],
    }
""",
        },
    ],
}


class WakeReviewer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAIJSONClient(settings) if settings.has_openai else None

    def _repo_snapshot(self, repo_root: Path) -> dict[str, Any]:
        tracked: list[str] = []
        preview_files: list[dict[str, str]] = []
        preview_paths: set[str] = set()
        ignored_parts = {".git", ".venv", "venv", "__pycache__", "doctor_local", ".pytest_cache", "build", "dist"}
        forced_preview_paths = set(ALLOWLISTED_RUNTIME_HELPERS)

        for path in sorted(repo_root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in ignored_parts for part in path.parts):
                continue

            rel = str(path.relative_to(repo_root))
            tracked.append(rel)

            should_preview = (
                rel in forced_preview_paths
                or (len(preview_files) < 40 and path.suffix in {".py", ".md", ".yml", ".yaml", ".toml", ".json"})
            )

            if should_preview and rel not in preview_paths:
                try:
                    preview_files.append(
                        {
                            "path": rel,
                            "content_preview": path.read_text(encoding="utf-8", errors="ignore")[:12000],
                        }
                    )
                    preview_paths.add(rel)
                except Exception:
                    continue

            if len(tracked) >= 250:
                break

        return {"tracked_files": tracked, "preview_files": preview_files}

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    def _normalize_path(self, path: str) -> str:
        cleaned = str(path or "").strip().replace("\\", "/")
        while "//" in cleaned:
            cleaned = cleaned.replace("//", "/")
        if cleaned.startswith("./"):
            cleaned = cleaned[2:]
        return cleaned

    def _normalize_phrase(self, text: str) -> str:
        cleaned = re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()
        return re.sub(r"\s+", " ", cleaned)

    def _semantic_tokens(self, text: str) -> set[str]:
        normalized = self._normalize_phrase(text)
        parts = normalized.split()

        canonical_map = {
            "wake": "wake_review",
            "review": "wake_review",
            "output": "review_contract",
            "outputs": "review_contract",
            "contract": "review_contract",
            "contracts": "review_contract",
            "invariant": "review_contract",
            "invariants": "review_contract",
            "safe": "safety_rule",
            "safely": "safety_rule",
            "safety": "safety_rule",
            "self": "self_evolution",
            "evolution": "self_evolution",
            "action": "action_requirement",
            "actions": "action_requirement",
            "exists": "existence_check",
            "exist": "existence_check",
            "existence": "existence_check",
            "ensure": "existence_check",
            "ensures": "existence_check",
            "ensuring": "existence_check",
            "require": "action_requirement",
            "requires": "action_requirement",
            "requirement": "action_requirement",
            "requirements": "action_requirement",
            "test": "test",
            "tests": "test",
            "regression": "regression_test",
            "rollback": "rollback",
            "rollback_metadata": "rollback",
            "rollbackmanifest": "rollback",
            "manifest": "rollback",
            "metadata": "metadata",
            "observability": "observability",
            "visibility": "observability",
            "alignment": "alignment",
            "schema": "schema",
            "protected": "protected_file",
            "guard": "guard",
            "guards": "guard",
            "filetools": "file_tools",
            "core": "protected_file",
            "trace": "trace",
            "logging": "observability",
            "runtime": "runtime",
            "telemetry": "observability",
            "error": "error",
            "digest": "digest",
            "failure": "failure",
            "failures": "failure",
            "run": "run",
            "health": "health",
            "success": "success",
            "document": "documentation",
            "documentation": "documentation",
            "docs": "documentation",
            "clarity": "documentation",
            "fallback": "fallback",
            "planner": "planner",
            "pressure": "pressure",
            "architecture": "architecture",
            "probe": "probe",
            "bundle": "bundle",
            "patch": "patch",
            "patches": "patch",
            "streak": "streak",
            "lane": "lane",
            "hint": "hint",
        }

        stopwords = {
            "add",
            "create",
            "introduce",
            "implement",
            "improve",
            "expand",
            "cover",
            "covers",
            "covering",
            "for",
            "the",
            "a",
            "an",
            "to",
            "of",
            "and",
            "that",
            "with",
            "within",
            "all",
            "current",
            "provided",
            "based",
            "ensure",
            "ensures",
            "ensuring",
        }

        tokens: set[str] = set()
        for part in parts:
            if not part or part in stopwords:
                continue
            tokens.add(canonical_map.get(part, part))

        if "wake_review" in tokens and "review_contract" in tokens:
            tokens.add("wake_review_contract_test")
        if "test" in tokens and "self_evolution" in tokens and "action_requirement" in tokens:
            tokens.add("self_evolution_action_test")
        if "test" in tokens and "existence_check" in tokens:
            tokens.add("existence_test")
        if "trace" in tokens and "observability" in tokens:
            tokens.add("trace_observability")
        if "runtime" in tokens and "observability" in tokens:
            tokens.add("runtime_observability")
        if "error" in tokens and "digest" in tokens:
            tokens.add("error_digest")
        if "run" in tokens and "health" in tokens:
            tokens.add("run_health")

        return tokens

    def _backlog_items_semantically_similar(self, left: str, right: str) -> bool:
        left_tokens = self._semantic_tokens(left)
        right_tokens = self._semantic_tokens(right)

        if not left_tokens or not right_tokens:
            return False

        overlap = left_tokens & right_tokens

        if "wake_review_contract_test" in overlap:
            return True
        if "self_evolution_action_test" in overlap and "test" in overlap:
            return True
        if {"test", "wake_review", "review_contract"} <= overlap:
            return True
        if {"test", "self_evolution", "action_requirement"} <= overlap:
            return True
        if {"rollback", "observability"} <= overlap:
            return True
        if "trace_observability" in overlap:
            return True

        similarity = len(overlap) / max(1, min(len(left_tokens), len(right_tokens)))
        return similarity >= 0.75

    def _tokenize_test_stem(self, path: str) -> set[str]:
        stem = Path(path).stem.lower()
        parts = re.split(r"[^a-z0-9]+", stem)
        stopwords = {
            "test",
            "tests",
            "wake",
            "review",
            "output",
            "outputs",
            "contract",
            "contracts",
            "safe",
            "action",
            "actions",
            "build",
            "plan",
            "plans",
            "invariant",
            "invariants",
            "regression",
        }
        return {part for part in parts if part and part not in stopwords}

    def _existing_backlog_items(self, memory_snapshot: dict[str, Any]) -> list[str]:
        items: list[str] = []

        for item in memory_snapshot.get("backlog", []) or []:
            text = str(item).strip()
            if text:
                items.append(text)

        reviews = memory_snapshot.get("architecture_reviews", []) or []
        for review in reviews[-6:]:
            if not isinstance(review, dict):
                continue
            for item in review.get("backlog_items", []) or []:
                text = str(item).strip()
                if text:
                    items.append(text)

        return items

    def _filter_repetitive_backlog_items(
        self,
        items: list[str],
        memory_snapshot: dict[str, Any],
    ) -> tuple[list[str], list[str]]:
        existing_items = self._existing_backlog_items(memory_snapshot)
        kept: list[str] = []
        removed: list[str] = []

        for item in items:
            text = str(item).strip()
            if not text:
                continue

            duplicate = False

            for prior in existing_items:
                if self._backlog_items_semantically_similar(text, prior):
                    duplicate = True
                    break

            if not duplicate:
                for prior in kept:
                    if self._backlog_items_semantically_similar(text, prior):
                        duplicate = True
                        break

            if duplicate:
                removed.append(text)
            else:
                kept.append(text)

        return kept, removed

    def _is_doc_or_observability_churn(self, text: str) -> bool:
        normalized = self._normalize_phrase(text)
        doc_markers = {
            "documentation",
            "docs",
            "clarity",
            "document",
            "explain",
            "comment",
            "comments",
        }
        obs_markers = {
            "observability",
            "logging",
            "trace",
            "diagnostic",
            "diagnostics",
            "metrics",
            "health checks",
            "health check",
        }
        return any(marker in normalized for marker in doc_markers) and any(
            marker in normalized for marker in obs_markers
        )

    def _suppress_noop_backlog_churn(
        self,
        review: ArchitectureReview,
    ) -> tuple[ArchitectureReview, bool]:
        if review.self_evolution_actions:
            return review, False

        kept: list[str] = []
        removed = False
        for item in review.backlog_items or []:
            if self._is_doc_or_observability_churn(item):
                removed = True
                continue
            kept.append(item)

        review.backlog_items = kept
        return review, removed

    def _is_test_only_action(self, action: SelfEvolutionAction) -> bool:
        if not action.patches:
            return False
        return all((self._normalize_path(patch.path or "")).startswith("tests/") for patch in action.patches)

    def _is_banned_test_path(self, path: str) -> bool:
        normalized = self._normalize_path(path).lower()
        return normalized in BANNED_TEST_PATH_PATTERNS

    def _has_banned_test_title(self, text: str) -> bool:
        normalized = self._normalize_phrase(text)
        return any(pattern in normalized for pattern in BANNED_TEST_TITLE_PATTERNS)

    def _is_banned_test_action(self, action: SelfEvolutionAction) -> bool:
        if self._has_banned_test_title(getattr(action, "title", "")):
            return True
        if self._has_banned_test_title(getattr(action, "description", "")):
            return True
        for patch in action.patches or []:
            if self._is_banned_test_path(getattr(patch, "path", "")):
                return True
        return False

    def _is_repetitive_test_action(self, action: SelfEvolutionAction, tracked_files: list[str]) -> bool:
        if not self._is_test_only_action(action):
            return False

        tracked_tests = [path for path in tracked_files if path.startswith("tests/")]

        for patch in action.patches:
            target = self._normalize_path(patch.path or "")
            if target in tracked_tests:
                return True

            target_tokens = self._tokenize_test_stem(target)
            if not target_tokens:
                continue

            for existing in tracked_tests:
                existing_tokens = self._tokenize_test_stem(existing)
                if not existing_tokens:
                    continue

                overlap = len(target_tokens & existing_tokens)
                smallest = min(len(target_tokens), len(existing_tokens))
                if smallest > 0 and overlap >= smallest:
                    return True

        return False

    def _is_banned_invented_filename(self, path: str, tracked_files: list[str]) -> bool:
        normalized = self._normalize_path(path)
        if normalized in tracked_files:
            return False
        filename = Path(normalized).name.lower()
        return filename in BANNED_INVENTED_MODULE_FILENAMES

    def _is_allowed_patch_path(self, path: str, tracked_files: list[str]) -> bool:
        normalized = self._normalize_path(path)

        if not normalized:
            return False
        if normalized in BANNED_SELF_EVOLUTION_PATHS:
            return False
        if self._is_banned_invented_filename(normalized, tracked_files):
            return False
        if normalized in tracked_files:
            return True
        if normalized in SAFE_NEW_FILE_ALLOWLIST:
            return True
        return False

    def _existing_file_text(self, repo_root: Path, path: str) -> str:
        normalized = self._normalize_path(path)
        if not normalized:
            return ""
        return self._read_text(repo_root / normalized)

    def _is_existing_runtime_helper_replace(self, repo_root: Path, patch: PatchAction) -> bool:
        normalized = self._normalize_path(getattr(patch, "path", ""))
        if normalized not in ALLOWLISTED_RUNTIME_HELPERS:
            return False
        if getattr(patch, "operation", "") != "replace_file":
            return False
        return (repo_root / normalized).exists()

    def _regex_patch_matches_current_file(self, repo_root: Path, patch: PatchAction) -> bool:
        if getattr(patch, "operation", "") != "regex_replace":
            return True

        normalized = self._normalize_path(getattr(patch, "path", ""))
        if not normalized:
            return False

        pattern = getattr(patch, "pattern", None)
        if not pattern:
            return False

        existing_text = self._existing_file_text(repo_root, normalized)
        if not existing_text:
            return False

        try:
            return re.search(pattern, existing_text, flags=re.MULTILINE | re.DOTALL) is not None
        except re.error:
            return False

    def _helper_rotation_order(self) -> list[str]:
        return [
            PROACTIVE_RUNTIME_PATH,
            ERROR_DIGEST_RUNTIME_PATH,
            RUN_HEALTH_RUNTIME_PATH,
            FALLBACK_RUNTIME_PATH,
            ARCHITECTURE_RUNTIME_PATH,
        ]

    def _recent_helper_paths(self, memory_snapshot: dict[str, Any], limit: int = 12) -> list[str]:
        recent: list[str] = []
        runs = memory_snapshot.get("runs", []) or []

        for run in reversed(runs[-limit:]):
            if not isinstance(run, dict):
                continue
            for patch in run.get("patches_applied", []) or []:
                if not isinstance(patch, dict):
                    continue
                path = self._normalize_path(str(patch.get("path", "")).strip())
                if path in ALLOWLISTED_RUNTIME_HELPERS and path not in recent:
                    recent.append(path)

        return recent

    def _helper_cooldown_paths(self, memory_snapshot: dict[str, Any], window: int = 2) -> set[str]:
        recent = self._recent_helper_paths(memory_snapshot, limit=max(window * 2, 6))
        return set(recent[:window])

    def _helper_path_allowed_by_rotation(
        self,
        *,
        patch_path: str,
        memory_snapshot: dict[str, Any],
    ) -> tuple[bool, str]:
        if patch_path not in ALLOWLISTED_RUNTIME_HELPERS:
            return True, ""

        cooldown_paths = self._helper_cooldown_paths(memory_snapshot, window=2)
        if patch_path not in cooldown_paths:
            return True, ""

        rotation = self._helper_rotation_order()
        for candidate in rotation:
            if candidate == patch_path:
                continue
            if candidate in cooldown_paths:
                continue
            return False, f"Cooldown active for {patch_path}; prefer rotating to {candidate} first."

        return False, f"Cooldown active for {patch_path}; all helper lanes were touched too recently."

    def _recent_helper_successes(self, memory_snapshot: dict[str, Any], limit: int = 8) -> dict[str, list[str]]:
        helper_events: dict[str, list[str]] = {}
        runs = memory_snapshot.get("runs", []) or []

        for run in runs[-limit:]:
            if not isinstance(run, dict):
                continue

            for patch in run.get("patches_applied", []) or []:
                if not isinstance(patch, dict):
                    continue

                path = self._normalize_path(str(patch.get("path", "")).strip())
                if path not in ALLOWLISTED_RUNTIME_HELPERS:
                    continue

                description = str(patch.get("description", "")).strip()
                if not description:
                    description = "applied helper patch"

                helper_events.setdefault(path, [])
                if description not in helper_events[path]:
                    helper_events[path].append(description)

        return helper_events

    def _recently_blocked_paths(self, memory_snapshot: dict[str, Any], limit: int = 6) -> dict[str, list[str]]:
        blocked: dict[str, list[str]] = {}

        runs = memory_snapshot.get("runs", []) or []
        for run in runs[-limit:]:
            if not isinstance(run, dict):
                continue

            for event in run.get("trace", []) or []:
                if not isinstance(event, dict):
                    continue
                if event.get("event") != "patch_apply_failed":
                    continue

                path = self._normalize_path(str(event.get("path", "")).strip())
                if not path:
                    continue

                error = str(event.get("error", "")).strip()
                if not error:
                    continue

                blocked.setdefault(path, [])
                if error not in blocked[path]:
                    blocked[path].append(error)

            self_evolution = run.get("self_evolution")
            if isinstance(self_evolution, dict):
                for reason in self_evolution.get("reasons", []) or []:
                    text = str(reason)
                    if "->" not in text:
                        continue
                    left, right = text.rsplit("->", 1)
                    path = self._normalize_path(right.strip())
                    if not path:
                        continue
                    blocked.setdefault(path, [])
                    if left.strip() not in blocked[path]:
                        blocked[path].append(left.strip())

        return blocked

    def _is_repeat_blocked_target(self, path: str, recently_blocked: dict[str, list[str]]) -> bool:
        normalized = self._normalize_path(path)
        reasons = recently_blocked.get(normalized, [])
        if not reasons:
            return False

        hot_reasons = (
            "replace on existing runtime helper",
            "shrink-replace",
            "pattern does not match",
            "regex_replace action whose pattern does not match",
            "blocked regex_replace",
            "blocked shrink-replace",
        )
        lowered = " | ".join(reasons).lower()
        return any(token in lowered for token in hot_reasons)

    def _count_helper_slots_present(self, existing_text: str, helper_path: str) -> int:
        count = 0
        for spec in HELPER_GROWTH_REGISTRY.get(helper_path, []):
            if f"def {spec['function_name']}(" in existing_text:
                count += 1
        return count

    def _helper_has_capacity(self, helper_path: str, existing_text: str) -> bool:
        cap = HELPER_SLOT_CAPS.get(helper_path, 0)
        present = self._count_helper_slots_present(existing_text, helper_path)
        return present < cap

    def _next_helper_growth_action(self, repo_root: Path, helper_path: str) -> SelfEvolutionAction | None:
        target = repo_root / helper_path
        existing = self._read_text(target)

        if target.exists() and not self._helper_has_capacity(helper_path, existing):
            return None

        for spec in HELPER_GROWTH_REGISTRY.get(helper_path, []):
            if f"def {spec['function_name']}(" in existing:
                continue

            if target.exists():
                return self._append_regex_patch_action(
                    path=helper_path,
                    title=spec["title"],
                    description=spec["description"],
                    function_name=spec["function_name"],
                    function_block=spec["function_block"],
                )

        return None

    def _proactive_runtime_action(self, repo_root: Path) -> SelfEvolutionAction | None:
        return self._next_helper_growth_action(repo_root, PROACTIVE_RUNTIME_PATH)

    def _error_digest_action(self, repo_root: Path) -> SelfEvolutionAction | None:
        return self._next_helper_growth_action(repo_root, ERROR_DIGEST_RUNTIME_PATH)

    def _run_health_action(self, repo_root: Path) -> SelfEvolutionAction | None:
        return self._next_helper_growth_action(repo_root, RUN_HEALTH_RUNTIME_PATH)

    def _fallback_patch_action(self, repo_root: Path) -> SelfEvolutionAction | None:
        return self._next_helper_growth_action(repo_root, FALLBACK_RUNTIME_PATH)

    def _default_build_action(self) -> PlannedWorkItem:
        return PlannedWorkItem(
            work_id="build-thread-001",
            title="Carry bounded maintenance forward",
            description="Keep a single small build thread active instead of idling.",
            mode="build",
            state="proposed",
            priority=1,
            route="safe",
            related_files=[
                PROACTIVE_RUNTIME_PATH,
                FALLBACK_RUNTIME_PATH,
                ARCHITECTURE_RUNTIME_PATH,
                ERROR_DIGEST_RUNTIME_PATH,
                RUN_HEALTH_RUNTIME_PATH,
            ],
            notes=[
                "Prefer bounded code patches over doc-only churn.",
                "Prefer allowlisted runtime helpers when reviewer drift is detected.",
                "Do not broaden scope when verification is failing.",
                "Do not use replace_file on an existing runtime helper.",
                "Do not propose regex_replace unless the pattern exists in the current file.",
                "Do not retry recently blocked targets immediately.",
                "Do not keep farming reviewer_fallback.py after it already exists.",
                "When no safe code action exists, prefer a clean no-op over documentation churn.",
            ],
        )

    def _derive_build_action(self, review: ArchitectureReview) -> PlannedWorkItem | None:
        if not review.self_evolution_actions:
            return None

        first_action = review.self_evolution_actions[0]
        related_files = [self._normalize_path(patch.path) for patch in first_action.patches if getattr(patch, "path", "")]
        if not related_files:
            return None

        title = first_action.title.strip() or "Carry bounded maintenance forward"
        description = first_action.description.strip() or "Apply the bounded self-evolution patch set."

        notes = [
            "Derived from reviewer-proposed self-evolution action.",
            "Keep the change bounded and verification-driven.",
            "Do not use replace_file on an existing runtime helper.",
            "Do not use regex_replace unless the pattern matches the current file.",
            "Do not retry recently blocked targets immediately.",
        ]

        return PlannedWorkItem(
            work_id="build-thread-derived-001",
            title=title[:120],
            description=description[:500],
            mode="build",
            state="proposed",
            priority=1,
            route="safe",
            related_files=related_files[:8],
            notes=notes,
        )

    def _default_architecture_plan(self, repo_root: Path) -> ArchitecturePlan | None:
        action = self._next_helper_growth_action(repo_root, ARCHITECTURE_RUNTIME_PATH)
        if action is None or not action.patches:
            return None

        return ArchitecturePlan(
            title=action.title,
            summary=action.description,
            rationale="Architecture mode should stay bounded and use existing helper-lane growth before broader structural work.",
            route="branch",
            files_touched=[self._normalize_path(p.path) for p in action.patches if getattr(p, "path", "")],
            patch_bundle=list(action.patches),
            status="proposed",
        )

    def _normalize_build_actions(self, review: ArchitectureReview) -> ArchitectureReview:
        normalized: list[PlannedWorkItem] = []

        for index, item in enumerate(review.build_actions or [], start=1):
            work_id = getattr(item, "work_id", "") or f"build-thread-auto-{index:03d}"
            title = (getattr(item, "title", "") or "Carry bounded maintenance forward").strip()
            description = (getattr(item, "description", "") or "Apply the bounded self-evolution patch set.").strip()
            mode = getattr(item, "mode", "build") or "build"
            state = getattr(item, "state", "proposed") or "proposed"
            priority = getattr(item, "priority", 1)
            route = getattr(item, "route", "safe") or "safe"
            related_files = list(getattr(item, "related_files", []) or [])
            notes = list(getattr(item, "notes", []) or [])

            normalized.append(
                PlannedWorkItem(
                    work_id=str(work_id),
                    title=title[:120],
                    description=description[:500],
                    mode=mode,
                    state=state,
                    priority=int(priority),
                    route=route,
                    related_files=related_files[:8],
                    notes=notes,
                )
            )

        review.build_actions = normalized
        return review

    def _review_from_payload(self, data: dict[str, Any]) -> ArchitectureReview:
        try:
            return ArchitectureReview.model_validate(data)
        except Exception:
            payload = dict(data or {})

            repaired_actions: list[dict[str, Any]] = []
            for index, item in enumerate(payload.get("build_actions", []) or [], start=1):
                if not isinstance(item, dict):
                    continue
                repaired = dict(item)
                repaired.setdefault("work_id", f"build-thread-auto-{index:03d}")
                repaired.setdefault("title", "Carry bounded maintenance forward")
                repaired.setdefault("description", "Apply the bounded self-evolution patch set.")
                repaired.setdefault("mode", "build")
                repaired.setdefault("state", "proposed")
                repaired.setdefault("priority", 1)
                repaired.setdefault("route", "safe")
                repaired.setdefault("related_files", [])
                repaired.setdefault("notes", [])
                repaired_actions.append(repaired)

            payload["build_actions"] = repaired_actions
            return ArchitectureReview.model_validate(payload)

    def _append_regex_patch_action(
        self,
        *,
        path: str,
        title: str,
        description: str,
        function_name: str,
        function_block: str,
    ) -> SelfEvolutionAction:
        return SelfEvolutionAction(
            title=title,
            description=description,
            risk="safe",
            patches=[
                PatchAction(
                    path=path,
                    operation="regex_replace",
                    pattern="\\Z",
                    replacement=function_block,
                    description=f"Append bounded helper function {function_name}.",
                )
            ],
        )

    def _recent_trace_summary(self, memory_snapshot: dict[str, Any], event_name: str, limit: int = 8) -> dict[str, Any] | None:
        runs = memory_snapshot.get("runs", []) or []
        for run in reversed(runs[-limit:]):
            if not isinstance(run, dict):
                continue
            for event in reversed(run.get("trace", []) or []):
                if not isinstance(event, dict):
                    continue
                if event.get("event") != event_name:
                    continue
                summary = event.get("summary")
                if isinstance(summary, dict):
                    return summary
        return None

    def _has_forced_helper_pressure(self, memory_snapshot: dict[str, Any]) -> bool:
        patch_velocity = self._recent_trace_summary(memory_snapshot, "runtime_patch_velocity_summary")
        build_pressure_summary = self._recent_trace_summary(memory_snapshot, "runtime_build_pressure_summary")
        build_action_summary = self._recent_trace_summary(memory_snapshot, "runtime_build_action_summary")

        if not patch_velocity:
            return False

        runs_with_patches = int(patch_velocity.get("runs_with_patches", 0) or 0)
        sample_size = int(patch_velocity.get("sample_size", 0) or 0)

        pressure_active = False
        if build_pressure_summary:
            pressure_active = bool(build_pressure_summary.get("active", False)) and int(build_pressure_summary.get("pressure_score", 0) or 0) > 0
        elif build_action_summary:
            pressure_active = int(build_action_summary.get("count", 0) or 0) > 0

        return sample_size > 0 and runs_with_patches == 0 and pressure_active

    def _forced_helper_priority_order(self) -> list[str]:
        return [
            ERROR_DIGEST_RUNTIME_PATH,
            RUN_HEALTH_RUNTIME_PATH,
            FALLBACK_RUNTIME_PATH,
            ARCHITECTURE_RUNTIME_PATH,
            PROACTIVE_RUNTIME_PATH,
        ]

    def _make_forced_helper_action(self, repo_root: Path, helper_path: str) -> SelfEvolutionAction | None:
        if helper_path == ERROR_DIGEST_RUNTIME_PATH:
            return self._error_digest_action(repo_root)
        if helper_path == RUN_HEALTH_RUNTIME_PATH:
            return self._run_health_action(repo_root)
        if helper_path == FALLBACK_RUNTIME_PATH:
            return self._fallback_patch_action(repo_root)
        if helper_path == PROACTIVE_RUNTIME_PATH:
            return self._proactive_runtime_action(repo_root)
        if helper_path == ARCHITECTURE_RUNTIME_PATH:
            plan = self._default_architecture_plan(repo_root)
            if isinstance(plan, ArchitecturePlan) and plan.patch_bundle:
                return SelfEvolutionAction(
                    title=plan.title,
                    description=plan.summary,
                    risk="safe",
                    patches=list(plan.patch_bundle),
                )
            return None
        return None

    def _forced_helper_pressure_action(
        self,
        *,
        repo_root: Path,
        memory_snapshot: dict[str, Any],
    ) -> tuple[SelfEvolutionAction | None, str, str]:
        cooldown_paths = self._helper_cooldown_paths(memory_snapshot, window=2)

        for helper_path in self._forced_helper_priority_order():
            if helper_path in cooldown_paths:
                continue
            action = self._make_forced_helper_action(repo_root, helper_path)
            if action is not None and bool(getattr(action, "patches", [])):
                return action, helper_path, "Forced bounded helper injection selected from runtime summary pressure."

        for helper_path in self._forced_helper_priority_order():
            action = self._make_forced_helper_action(repo_root, helper_path)
            if action is not None and bool(getattr(action, "patches", [])):
                return action, helper_path, "Forced bounded helper injection selected after exhausting cooldown-safe helper lanes."

        return None, "", ""

    def _bridge_build_pressure_action(
        self,
        *,
        repo_root: Path,
        memory_snapshot: dict[str, Any],
    ) -> tuple[SelfEvolutionAction | None, str, str]:
        pressure_summary = self._recent_trace_summary(memory_snapshot, "runtime_build_pressure_summary")
        if not pressure_summary:
            return None, "", ""

        related_files = [str(path).strip() for path in pressure_summary.get("related_files", []) or [] if str(path).strip()]
        if not related_files:
            return None, "", ""

        helper_map = {
            ERROR_DIGEST_RUNTIME_PATH: ERROR_DIGEST_RUNTIME_PATH,
            RUN_HEALTH_RUNTIME_PATH: RUN_HEALTH_RUNTIME_PATH,
            FALLBACK_RUNTIME_PATH: FALLBACK_RUNTIME_PATH,
            ARCHITECTURE_RUNTIME_PATH: ARCHITECTURE_RUNTIME_PATH,
            PROACTIVE_RUNTIME_PATH: PROACTIVE_RUNTIME_PATH,
        }

        for related_path in related_files:
            normalized = self._normalize_path(related_path)
            helper_path = helper_map.get(normalized)
            if not helper_path:
                continue
            action = self._make_forced_helper_action(repo_root, helper_path)
            if action is not None and bool(getattr(action, "patches", [])):
                return action, helper_path, "Grounded build-pressure bridge converted helper intent into a concrete bounded patch."

        if PROACTIVE_RUNTIME_PATH in related_files or any(self._normalize_path(path) == PROACTIVE_RUNTIME_PATH for path in related_files):
            action = self._make_forced_helper_action(repo_root, PROACTIVE_RUNTIME_PATH)
            if action is not None and bool(getattr(action, "patches", [])):
                return action, PROACTIVE_RUNTIME_PATH, "Grounded build-pressure bridge used trace summary helper contents from disk to construct a concrete bounded patch."

        return None, "", ""

    def _synthesize_action_from_build_pressure(
        self,
        *,
        repo_root: Path,
        memory_snapshot: dict[str, Any],
    ) -> tuple[SelfEvolutionAction | None, str, str]:
        pressure_summary = self._recent_trace_summary(memory_snapshot, "runtime_build_pressure_summary")
        if not pressure_summary:
            return None, "", ""

        if not bool(pressure_summary.get("active", False)):
            return None, "", ""

        related_files = [
            self._normalize_path(path)
            for path in (pressure_summary.get("related_files", []) or [])
            if str(path).strip()
        ]
        if not related_files:
            return None, "", ""

        helper_map = {
            PROACTIVE_RUNTIME_PATH: lambda: self._proactive_runtime_action(repo_root),
            ERROR_DIGEST_RUNTIME_PATH: lambda: self._error_digest_action(repo_root),
            RUN_HEALTH_RUNTIME_PATH: lambda: self._run_health_action(repo_root),
            FALLBACK_RUNTIME_PATH: lambda: self._fallback_patch_action(repo_root),
            ARCHITECTURE_RUNTIME_PATH: lambda: (
                SelfEvolutionAction(
                    title=plan.title,
                    description=plan.summary,
                    risk="safe",
                    patches=list(plan.patch_bundle),
                )
                if (plan := self._default_architecture_plan(repo_root)) is not None and plan.patch_bundle
                else None
            ),
        }

        for helper_path in related_files:
            factory = helper_map.get(helper_path)
            if not factory:
                continue
            action = factory()
            if action is not None and bool(getattr(action, "patches", [])):
                return (
                    action,
                    helper_path,
                    "Synthesized bounded self-evolution action directly from normalized build-pressure summary.",
                )

        return None, "", ""

    def _filter_low_value_actions(
        self,
        actions: list[SelfEvolutionAction],
        tracked_files: list[str],
        repo_root: Path,
        memory_snapshot: dict[str, Any],
    ) -> tuple[list[SelfEvolutionAction], list[str]]:
        kept: list[SelfEvolutionAction] = []
        removed_notes: list[str] = []
        recently_blocked = self._recently_blocked_paths(memory_snapshot)

        for action in actions:
            if self._is_banned_test_action(action):
                removed_notes.append(f"Blocked permanently banned test-loop action: {action.title}")
                continue

            if self._is_repetitive_test_action(action, tracked_files):
                removed_notes.append(f"Suppressed repetitive test-only self-evolution action: {action.title}")
                continue

            invalid_paths: list[str] = []
            existing_replace_paths: list[str] = []
            missing_regex_anchor_paths: list[str] = []
            repeated_blocked_paths: list[str] = []
            repetitive_fallback_paths: list[str] = []
            cooldown_blocked_helper_paths: list[str] = []
            cooldown_notes: list[str] = []

            for patch in action.patches or []:
                patch_path = self._normalize_path(getattr(patch, "path", ""))

                if not self._is_allowed_patch_path(patch_path, tracked_files):
                    invalid_paths.append(patch_path)
                    continue

                if patch_path == FALLBACK_RUNTIME_PATH and patch_path in tracked_files:
                    repetitive_fallback_paths.append(patch_path)
                    continue

                if self._is_repeat_blocked_target(patch_path, recently_blocked):
                    repeated_blocked_paths.append(patch_path)
                    continue

                allowed_by_rotation, cooldown_note = self._helper_path_allowed_by_rotation(
                    patch_path=patch_path,
                    memory_snapshot=memory_snapshot,
                )
                if not allowed_by_rotation:
                    cooldown_blocked_helper_paths.append(patch_path)
                    if cooldown_note:
                        cooldown_notes.append(cooldown_note)
                    continue

                if self._is_existing_runtime_helper_replace(repo_root, patch):
                    existing_replace_paths.append(patch_path)
                    continue

                if not self._regex_patch_matches_current_file(repo_root, patch):
                    missing_regex_anchor_paths.append(patch_path)

            if invalid_paths:
                removed_notes.append(
                    f"Blocked self-evolution action with non-tracked, banned, or non-allowlisted paths: {action.title} -> {', '.join(invalid_paths)}"
                )
                continue

            if repetitive_fallback_paths:
                removed_notes.append(
                    f"Blocked repetitive fallback-helper farming: {action.title} -> {', '.join(repetitive_fallback_paths)}"
                )
                continue

            if repeated_blocked_paths:
                removed_notes.append(
                    f"Blocked retry of recently-failed target: {action.title} -> {', '.join(repeated_blocked_paths)}"
                )
                continue

            if cooldown_blocked_helper_paths:
                extra = f" ({' | '.join(cooldown_notes)})" if cooldown_notes else ""
                removed_notes.append(
                    f"Suppressed helper churn during cooldown window: {action.title} -> {', '.join(cooldown_blocked_helper_paths)}{extra}"
                )
                continue

            if existing_replace_paths:
                removed_notes.append(
                    f"Blocked replace_file on existing runtime helper: {action.title} -> {', '.join(existing_replace_paths)}"
                )
                continue

            if missing_regex_anchor_paths:
                removed_notes.append(
                    f"Blocked regex_replace action whose pattern does not match current file: {action.title} -> {', '.join(missing_regex_anchor_paths)}"
                )
                continue

            kept.append(action)

        return kept, removed_notes

    def _force_allowlisted_action_only(self, review: ArchitectureReview, repo_root: Path) -> ArchitectureReview:
        proactive_action = self._proactive_runtime_action(repo_root)
        run_health_action = self._run_health_action(repo_root)
        digest_action = self._error_digest_action(repo_root)
        fallback_action = self._fallback_patch_action(repo_root)

        if proactive_action is not None:
            review.self_evolution_actions = [proactive_action]
            review.build_actions = [self._derive_build_action(review) or self._default_build_action()]
            review.execution_notes.append(
                "Reviewer output drifted onto invalid targets; replaced with allowlisted proactive runtime helper."
            )
            return review

        if run_health_action is not None:
            review.self_evolution_actions = [run_health_action]
            review.build_actions = [self._derive_build_action(review) or self._default_build_action()]
            review.execution_notes.append(
                "Reviewer output drifted onto invalid targets; replaced with allowlisted run-health runtime helper."
            )
            return review

        if digest_action is not None:
            review.self_evolution_actions = [digest_action]
            review.build_actions = [self._derive_build_action(review) or self._default_build_action()]
            review.execution_notes.append(
                "Reviewer output drifted onto invalid targets; replaced with allowlisted error-digest runtime helper."
            )
            return review

        if fallback_action is not None:
            review.self_evolution_actions = [fallback_action]
            review.build_actions = [self._derive_build_action(review) or self._default_build_action()]
            review.execution_notes.append(
                "Reviewer output drifted onto invalid targets; replaced with allowlisted fallback runtime helper."
            )
            return review

        review.self_evolution_actions = []
        review.execution_notes.append(
            "Reviewer output drifted onto invalid targets and no allowlisted helper remained available."
        )
        return review

    def _build_prompt(
        self,
        memory_snapshot: dict[str, Any],
        repo_snapshot: dict[str, Any],
        recent_summary: str,
    ) -> str:
        memory_json = json.dumps(memory_snapshot, indent=2)[:18000]
        repo_json = json.dumps(repo_snapshot, indent=2)[:26000]

        allowlisted_new_files = "\n".join(f"  * {path}" for path in sorted(SAFE_NEW_FILE_ALLOWLIST))
        banned_paths = "\n".join(f"  * {path}" for path in sorted(BANNED_SELF_EVOLUTION_PATHS))
        banned_filenames = "\n".join(f"  * {name}" for name in sorted(BANNED_INVENTED_MODULE_FILENAMES))

        return f"""You are the wake-review agent for a bounded self-maintenance repository.

Return valid JSON only.

Rules:
- Output MUST match the requested schema exactly.
- Prefer one small executable Python patch over documentation-only output when possible.
- Only emit safe, bounded changes.
- Never emit secrets handling, destructive shell commands, dependency explosions, or large rewrites.
- If you emit any self_evolution_actions, also emit at least one matching build_action that describes carrying that patch set forward.
- Only emit architecture_plans when there is a genuine repo-wide structural issue that should be handled in a branch lane.
- If there is no justified architecture plan, return an empty architecture_plans array.
- Keep build_actions concrete, file-aware, and aligned to the self_evolution_actions when present.
- Do not invent architecture work just to fill the field.
- Avoid repetitive low-value maintenance loops.
- NEVER propose any wake-review invariant test, wake-review output test, wake-review contract test, or self-evolution action existence test.
- NEVER propose tests targeting:
  * tests/test_wake_review_invariant.py
  * tests/test_wake_review_invariants.py
  * tests/test_wake_review_output.py
  * tests/test_wake_review_contract.py
  * tests/test_self_evolution.py
- Do not propose a new regression test if a materially similar test already exists in tests/.
- Do not repeat backlog items that are already present in memory unless there is genuinely new evidence.
- Treat these as permanently banned low-value loops:
  * wake-review invariant test
  * wake-review output test
  * wake-review contract test
  * self-evolution action existence test
- Prefer source/runtime fixes over another tiny documentation or test-only loop when the system is already green.
- Even when the repo is green, proactively propose one bounded runtime, observability, or safety improvement if a non-repetitive one exists.
- Prefer runtime/observability helpers over tests when no failures exist.
- CRITICAL: every self_evolution patch path MUST be either:
  * an existing tracked file from the repository snapshot, or
  * one of these allowlisted new files only:
{allowlisted_new_files}
- CRITICAL: NEVER target these banned self-evolution paths:
{banned_paths}
- CRITICAL: NEVER invent these module filenames unless that exact full path already exists in tracked_files:
{banned_filenames}
- NEVER invent a new module name like logging_utils.py, reviewer.py, helper.py, utils.py, or similar unless that exact path already exists in tracked_files.
- If you cannot justify a patch against an existing tracked file, use one of the allowlisted runtime helper paths above.
- Strong preference: if your idea is “better logging/observability,” target the allowlisted runtime helper files first, not a new module.
- CRITICAL: if an allowlisted runtime helper file already exists, do not use replace_file against it.
- CRITICAL: for an existing runtime helper file, either use regex_replace with a pattern that exists in the file or leave self_evolution_actions empty.
- IMPORTANT: the repository snapshot preview and the on-disk helper file at repo_root count as current file contents. Do not say the file contents were 'not provided' when the helper exists in tracked_files and its preview/content can be read from disk.
- CRITICAL: do not retry the same target if it was recently blocked for replace-on-existing-helper, shrink-replace, or missing regex anchor.
- CRITICAL: do not keep proposing reviewer_fallback.py once that file already exists.
- Prefer a fresh allowlisted helper before repeating stale runtime-helper ideas.
- If no valid self_evolution patch target exists, return an empty self_evolution_actions array and avoid documentation-only churn.
- If recent runtime summaries indicate flat patch velocity and non-empty build-action pressure, prefer emitting one cooldown-allowed bounded helper action rather than a no-op.
- Helper growth is finite and must stay inside the allowlisted runtime-helper lane before any broader source changes are considered.

Required JSON shape:
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
          "path": "string",
          "operation": "replace_file",
          "new_content": "string",
          "pattern": null,
          "replacement": null,
          "description": "string"
        }}
      ]
    }}
  ],
  "build_actions": [
    {{
      "work_id": "string",
      "title": "string",
      "description": "string",
      "mode": "build",
      "state": "proposed",
      "priority": 1,
      "route": "safe",
      "related_files": ["string"],
      "notes": ["string"],
      "created_at": "ISO timestamp",
      "updated_at": "ISO timestamp"
    }}
  ],
  "architecture_plans": [
    {{
      "title": "string",
      "summary": "string",
      "rationale": "string",
      "route": "branch",
      "files_touched": ["string"],
      "patch_bundle": [
        {{
          "path": "string",
          "operation": "replace_file",
          "new_content": "string",
          "pattern": null,
          "replacement": null,
          "description": "string"
        }}
      ],
      "proof_requirements": ["string"],
      "status": "proposed",
      "created_at": "ISO timestamp",
      "updated_at": "ISO timestamp"
    }}
  ],
  "execution_notes": ["string"],
  "risk_level": "low"
}}

Recent summary:
{recent_summary}

Current memory snapshot:
{memory_json}

Repository snapshot:
{repo_json}
"""

    def _fallback_review(self, repo_root: Path, reason: str) -> ArchitectureReview:
        proactive_action = self._proactive_runtime_action(repo_root)
        run_health_action = self._run_health_action(repo_root)
        digest_action = self._error_digest_action(repo_root)
        fallback_action = self._fallback_patch_action(repo_root)
        fallback_plan = self._default_architecture_plan(repo_root)

        actions: list[SelfEvolutionAction] = []
        if proactive_action is not None:
            actions.append(proactive_action)
        elif run_health_action is not None:
            actions.append(run_health_action)
        elif digest_action is not None:
            actions.append(digest_action)
        elif fallback_action is not None:
            actions.append(fallback_action)

        plans = [fallback_plan] if fallback_plan is not None else []

        execution_notes = ["Fallback review used because model output was unavailable or invalid."]
        if proactive_action is not None:
            execution_notes.append("Proactive runtime improvement injected while repo is otherwise healthy.")
        elif run_health_action is not None:
            execution_notes.append("Run-health runtime improvement injected while repo is otherwise healthy.")
        elif digest_action is not None:
            execution_notes.append("Error-digest runtime improvement injected while repo is otherwise healthy.")

        return ArchitectureReview(
            diagnosis="Fallback review generated",
            system_intent="Keep the agent bounded, testable, patch-capable, proactive, and anti-loop.",
            strengths=["Repository is reachable and reviewer fallback is active."],
            weaknesses=[reason],
            recommendations=["Stabilise reviewer schema and runtime alignment."],
            backlog_items=[
                "Tighten schema alignment between reviewer, planner, and engine.",
                "Continue prioritizing helper-lane observability improvements over repetitive wake-review test churn.",
                "Keep helper growth finite and inside the allowlisted helper lane.",
            ],
            self_evolution_actions=actions,
            build_actions=[self._default_build_action()],
            architecture_plans=plans,
            execution_notes=execution_notes,
            risk_level="low",
        )

    def review(self, memory_snapshot: dict[str, Any], repo_root: Path, recent_summary: str) -> ArchitectureReview:
        if self.client is None:
            return self._fallback_review(repo_root, "OpenAI client unavailable.")

        repo_snapshot = self._repo_snapshot(repo_root)
        prompt = self._build_prompt(memory_snapshot, repo_snapshot, recent_summary)

        try:
            data = self.client.generate_json(
                model=self.settings.openai_model_review,
                system=(
                    "You are a strict JSON-only architecture reviewer. "
                    "Return only a valid JSON object matching the provided schema. "
                    "When you propose a self-evolution action, include a matching build_action. "
                    "Only include architecture_plans when clearly justified by a repo-wide structural issue. "
                    "Avoid repetitive low-value test or backlog churn. "
                    "Never propose wake-review invariant/output/contract tests or self-evolution existence tests. "
                    "Do not invent new file targets unless they are explicitly allowlisted runtime helper paths. "
                    "Do not target banned self-evolution paths. "
                    "Prefer allowlisted runtime helper paths for observability improvements. "
                    "For an existing runtime helper file, do not use replace_file. "
                    "For an existing runtime helper file, prefer regex_replace when the pattern matches the current file. Prefer appending a small helper function to an existing runtime helper over returning no action. "
                    "Do not retry recently blocked targets. "
                    "Do not keep proposing reviewer_fallback.py once it already exists. "
                    "Prefer a fresh allowlisted helper before repeating stale helper ideas. "
                    "When the repo is green, still look for one bounded runtime, observability, or safety improvement. Treat repository snapshot previews and on-disk helper files as grounded current contents for regex_replace decisions; do not claim an existing helper's contents are unavailable if it is already in tracked_files. "
                    "If no safe code action exists, prefer a clean no-op over documentation-only churn, except when recent runtime summaries show flat patch velocity with active build-action pressure, in which case emit one cooldown-allowed bounded helper action. "
                    "Helper growth is finite and must stay inside the helper lane."
                ),
                prompt=prompt,
                schema=ArchitectureReview.model_json_schema(),
            )
            review = self._review_from_payload(data)
        except Exception as exc:
            print(f"[REVIEWER ERROR] {type(exc).__name__}: {exc}", flush=True)
            return self._fallback_review(repo_root, f"Reviewer model call failed: {type(exc).__name__}: {exc}")

        tracked_files = repo_snapshot.get("tracked_files", []) or []
        filtered_actions, action_notes = self._filter_low_value_actions(
            review.self_evolution_actions,
            tracked_files,
            repo_root,
            memory_snapshot,
        )
        review.self_evolution_actions = filtered_actions
        if action_notes:
            review.execution_notes.extend(action_notes)

        filtered_backlog, removed_backlog = self._filter_repetitive_backlog_items(
            review.backlog_items,
            memory_snapshot,
        )
        review.backlog_items = filtered_backlog
        if removed_backlog:
            review.execution_notes.append("Suppressed repetitive backlog items already present in memory.")

        review, removed_noop_churn = self._suppress_noop_backlog_churn(review)
        if removed_noop_churn:
            review.execution_notes.append("Suppressed documentation/observability backlog churn because no safe code action existed.")

        if review.self_evolution_actions:
            only_allowlisted_or_tracked = True
            for action in review.self_evolution_actions:
                for patch in action.patches or []:
                    patch_path = self._normalize_path(getattr(patch, "path", ""))
                    if not self._is_allowed_patch_path(patch_path, tracked_files):
                        only_allowlisted_or_tracked = False
                        break
                if not only_allowlisted_or_tracked:
                    break

            if not only_allowlisted_or_tracked:
                review = self._force_allowlisted_action_only(review, repo_root)

        if not review.build_actions:
            derived_action = self._derive_build_action(review)
            if derived_action is not None:
                review.build_actions = [derived_action]
                review.execution_notes.append("Derived build action injected from reviewer-proposed self-evolution patch set.")
            else:
                review.build_actions = [self._default_build_action()]
                review.execution_notes.append("Default build action injected because reviewer returned none.")

        forced_pressure = self._has_forced_helper_pressure(memory_snapshot)

        if forced_pressure:
            forced_action, forced_path, forced_note = self._forced_helper_pressure_action(
                repo_root=repo_root,
                memory_snapshot=memory_snapshot,
            )
            if forced_action is None or not bool(getattr(forced_action, "patches", [])):
                forced_action, forced_path, forced_note = self._bridge_build_pressure_action(
                    repo_root=repo_root,
                    memory_snapshot=memory_snapshot,
                )
            if forced_action is not None and bool(getattr(forced_action, "patches", [])):
                review.self_evolution_actions = [forced_action]
                review.execution_notes.append(
                    "Forced helper override engaged due to flat patch velocity + active build pressure."
                )
                if forced_note:
                    review.execution_notes.append(forced_note)
                if forced_path:
                    review.execution_notes.append(f"Forced helper target: {forced_path}")

        if not review.self_evolution_actions and self._has_forced_helper_pressure(memory_snapshot):
            pressure_action, pressure_path, pressure_note = self._synthesize_action_from_build_pressure(
                repo_root=repo_root,
                memory_snapshot=memory_snapshot,
            )
            if pressure_action is not None and bool(getattr(pressure_action, "patches", [])):
                review.self_evolution_actions = [pressure_action]
                review.execution_notes.append(
                    "Planner-held build pressure synthesized a bounded self-evolution action before fallback no-op resolution."
                )
                if pressure_note:
                    review.execution_notes.append(pressure_note)
                if pressure_path:
                    review.execution_notes.append(f"Pressure-synthesized helper target: {pressure_path}")
                review.execution_notes.append(
                    "Normalized build-pressure signal converted directly into a concrete helper patch."
                )

        if not review.self_evolution_actions:
            helper_candidates = {
                RUN_HEALTH_RUNTIME_PATH: (self._run_health_action(repo_root), "Run-health runtime improvement injected while repo is green."),
                FALLBACK_RUNTIME_PATH: (self._fallback_patch_action(repo_root), "Fallback self-evolution patch injected because reviewer returned no executable patch."),
                ARCHITECTURE_RUNTIME_PATH: (self._default_architecture_plan(repo_root), "Architecture-probe helper candidate selected for bounded branch-safe observability."),
                PROACTIVE_RUNTIME_PATH: (self._proactive_runtime_action(repo_root), "Proactive runtime improvement injected while repo is green."),
                ERROR_DIGEST_RUNTIME_PATH: (self._error_digest_action(repo_root), "Error-digest runtime improvement injected while repo is green."),
            }
            preferred_order = [
                RUN_HEALTH_RUNTIME_PATH,
                FALLBACK_RUNTIME_PATH,
                ARCHITECTURE_RUNTIME_PATH,
                PROACTIVE_RUNTIME_PATH,
                ERROR_DIGEST_RUNTIME_PATH,
            ]
            cooldown_paths = self._helper_cooldown_paths(memory_snapshot, window=2)

            chosen_action: SelfEvolutionAction | None = None
            chosen_note = ""
            chosen_path = ""

            for helper_path in preferred_order:
                candidate, note = helper_candidates.get(helper_path, (None, ""))
                if candidate is None:
                    continue
                if helper_path in cooldown_paths:
                    continue

                if helper_path == ARCHITECTURE_RUNTIME_PATH and isinstance(candidate, ArchitecturePlan):
                    if candidate.patch_bundle:
                        chosen_action = SelfEvolutionAction(
                            title=candidate.title,
                            description=candidate.summary,
                            risk="safe",
                            patches=list(candidate.patch_bundle),
                        )
                        chosen_note = note
                        chosen_path = helper_path
                        break
                    continue

                if isinstance(candidate, SelfEvolutionAction) and bool(getattr(candidate, "patches", [])):
                    chosen_action = candidate
                    chosen_note = note
                    chosen_path = helper_path
                    break

            if chosen_action is not None:
                review.self_evolution_actions = [chosen_action]
                if chosen_note:
                    review.execution_notes.append(chosen_note)
                if chosen_path:
                    review.execution_notes.append(f"Cooldown-aware helper injection selected: {chosen_path}")

        if review.architecture_plans:
            justified_plans: list[ArchitecturePlan] = []
            for plan in review.architecture_plans:
                valid_paths = [
                    self._normalize_path(path)
                    for path in (plan.files_touched or [])
                    if self._is_allowed_patch_path(path, tracked_files)
                ]
                valid_bundle = [
                    patch
                    for patch in (plan.patch_bundle or [])
                    if self._is_allowed_patch_path(getattr(patch, "path", ""), tracked_files)
                ]
                if valid_paths and valid_bundle:
                    plan.files_touched = valid_paths
                    plan.patch_bundle = valid_bundle
                    justified_plans.append(plan)
            review.architecture_plans = justified_plans

        review = self._normalize_build_actions(review)
        return review