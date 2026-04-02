from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import DaddyEngine
from .logging_utils import console
from .models import ExternalProposal


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="daddy", description="The Daddy debugging swarm")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run", help="Run full wake-review-debug cycle")

    submit = sub.add_parser("submit-proposal", help="Submit unknown external agent proposal for vetting")
    submit.add_argument("--agent-id", required=True)
    submit.add_argument("--file", required=True, help="Path to proposal JSON file")
    submit.add_argument("--title", default="External proposal")
    submit.add_argument("--summary", default="Imported from file")

    inspect = sub.add_parser("memory", help="Print current memory snapshot")
    inspect.add_argument("--pretty", action="store_true")

    return parser


def main() -> int:
    args = build_parser().parse_args()
    engine = DaddyEngine()

    if args.command == "run":
        record = engine.run()
        console.print_json(data=record.model_dump(mode="json"))
        return 0 if record.success else 1

    if args.command == "submit-proposal":
        payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
        proposal = ExternalProposal(
            agent_id=args.agent_id,
            title=args.title,
            summary=args.summary,
            payload=payload,
            proposed_changes=payload.get("proposed_changes", []) if isinstance(payload, dict) else [],
        )
        result = engine.vet_external_proposal(proposal)
        console.print_json(data=result)
        return 0

    if args.command == "memory":
        data = engine.memory.state.model_dump(mode="json")
        if args.pretty:
            console.print_json(data=data)
        else:
            print(json.dumps(data))
        return 0

    return 1
