#!/usr/bin/env python3
"""attempt_real_repair.py — Standalone repair entry-point for THEY-CALL-ME-THE-DADDY.

Usage:
    python attempt_real_repair.py [--dry-run] [--skip-recheck]

Workflow:
    1. Run the project test suite (pytest -q).
    2. If all tests pass, exit 0 — nothing to repair.
    3. On failure, invoke the DaddyEngine so it can propose and apply a bounded
       repair patch using the existing upgrade-gate / repair-mode infrastructure.
    4. Re-run pytest to confirm the repair worked.
    5. Exit 0 on success, 1 on failure.

Environment variables honoured by DaddyEngine (passed through automatically):
    OPENAI_API_KEY, GITHUB_TOKEN, GITHUB_REPO, R2_*, DADDY_* — see config.py.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_tests(label: str = "tests") -> tuple[int, str]:
    """Run pytest and return (returncode, combined output)."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=short"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    output = (result.stdout or "") + (result.stderr or "")
    print(f"--- {label} output ---")
    print(output.rstrip())
    print(f"--- returncode: {result.returncode} ---")
    return result.returncode, output


def _attempt_engine_repair() -> dict:
    """Invoke DaddyEngine.run() and return a summary dict."""
    # Ensure the src layout is importable even when called directly.
    src_path = str(ROOT / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    from the_daddy.config import Settings  # noqa: PLC0415
    from the_daddy.engine import DaddyEngine  # noqa: PLC0415

    settings = Settings()
    engine = DaddyEngine(settings)
    record = engine.run()

    patches_applied = getattr(record, "patches_applied", []) or []
    return {
        "run_id": getattr(record, "run_id", ""),
        "success": bool(getattr(record, "success", False)),
        "summary": str(getattr(record, "summary", "")),
        "selected_mode": str(getattr(record, "selected_mode", "")),
        "patch_count": len(patches_applied),
        "changed_files": [
            p.get("path", "") if isinstance(p, dict) else getattr(p, "path", "")
            for p in patches_applied
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Attempt real repair: run tests, fix on failure, re-verify."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run tests and report status without invoking the engine.",
    )
    parser.add_argument(
        "--skip-recheck",
        action="store_true",
        help="Skip the post-repair test re-run.",
    )
    args = parser.parse_args()

    # Step 1 — pre-check
    print("=" * 60)
    print("attempt_real_repair: pre-check")
    print("=" * 60)
    rc, _ = _run_tests("pre-repair tests")

    if rc == 0:
        print("\n✓ Tests pass — no repair needed.")
        return 0

    print(f"\n✗ Tests failed (rc={rc}).")

    if args.dry_run:
        print("--dry-run: skipping engine repair.")
        return 1

    # Step 2 — engine repair
    print("\n" + "=" * 60)
    print("attempt_real_repair: invoking DaddyEngine")
    print("=" * 60)

    try:
        result = _attempt_engine_repair()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Failed to invoke DaddyEngine for repair: {exc}", file=sys.stderr)
        return 1

    print("\nEngine result:")
    print(json.dumps(result, indent=2))

    engine_succeeded = bool(result.get("success"))
    if not engine_succeeded:
        print(f"\n✗ Engine repair did not succeed: {result.get('summary', '')}")

    if args.skip_recheck:
        return 0 if engine_succeeded else 1

    # Step 3 — post-repair verification
    # Always re-run tests when not skipping, even if the engine reported failure —
    # a partial patch may still have resolved the original breakage.
    print("\n" + "=" * 60)
    print("attempt_real_repair: post-repair verification")
    print("=" * 60)
    rc_post, _ = _run_tests("post-repair tests")

    if rc_post == 0:
        print("\n✓ Post-repair verification passed.")
        return 0

    print(f"\n✗ Post-repair verification failed (rc={rc_post}).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
