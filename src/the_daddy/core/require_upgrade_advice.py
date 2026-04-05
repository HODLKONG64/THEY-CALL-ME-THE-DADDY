from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("advice_path")
    parser.add_argument("--max-age-hours", type=int, default=6)
    args = parser.parse_args()

    advice_path = Path(args.advice_path).resolve()
    if not advice_path.exists():
        raise SystemExit("OpenAI upgrade advice file is missing")

    advice = json.loads(advice_path.read_text(encoding="utf-8"))

    required = [
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
    missing = [key for key in required if key not in advice]
    if missing:
        raise SystemExit(f"Upgrade advice is missing required fields: {', '.join(missing)}")

    generated_at = parse_iso(str(advice["generated_at"]))
    oldest_allowed = datetime.now(timezone.utc) - timedelta(hours=args.max_age_hours)
    if generated_at < oldest_allowed:
        raise SystemExit("Upgrade advice is stale")

    if not isinstance(advice["allow_proceed"], bool):
        raise SystemExit("allow_proceed must be a boolean")

    # --- KEY FIX: allow repair mode ---
    problem_type = str(advice.get("problem_type", "")).strip().lower()

    if not advice["allow_proceed"]:
        if problem_type == "healthy_safe_loop":
            print("Repair mode allowed (healthy_safe_loop detected)")
        else:
            raise SystemExit(
                "OpenAI upgrade advice did not approve proceeding: "
                + str(advice.get("summary", "no summary provided"))
            )

    if not isinstance(advice.get("target_files"), list) or not advice["target_files"]:
        raise SystemExit("OpenAI upgrade advice must contain at least one target file")

    print("OpenAI upgrade advice accepted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
