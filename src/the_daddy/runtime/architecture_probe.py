from __future__ import annotations

from typing import Any


def architecture_probe_summary(summary: str, files_touched: list[str] | None = None) -> dict[str, Any]:
    return {
        "summary": summary,
        "files_touched": files_touched or [],
        "source": "architecture_probe",
    }


def summarize_architecture_targets(files_touched: list[str] | None = None) -> dict[str, Any]:
    items = [str(item).strip() for item in (files_touched or []) if str(item).strip()]
    return {
        "target_count": len(items),
        "targets": items,
        "first_target": items[0] if items else "",
    }


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


def summarize_architecture_bundle_density(patch_bundle: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = patch_bundle or []
    return {
        "patch_count": len(items),
        "paths": [str(item.get("path", "")).strip() for item in items if str(item.get("path", "")).strip()][:10],
    }


def summarize_helper_lane_target_probe(trace: list[dict] | None = None) -> dict:
    items = trace or []
    generated = [
        str(e.get('chosen_path', ''))
        for e in items
        if e.get('event') == 'safe_helper_lane_patch_generated'
        and e.get('chosen_path')
    ]
    return {
        "helper_lane_generated_count": len(generated),
        "chosen_paths": generated[:10],
    }
