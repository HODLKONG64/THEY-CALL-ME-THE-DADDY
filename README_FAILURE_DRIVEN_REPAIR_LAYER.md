# Failure-Driven Repair Layer

This bundle builds on the current working build and adds the next repair-intelligence step.

## Added
- `src/the_daddy/core/failure_parser.py`

## Updated
- `src/the_daddy/agents/reviewer.py`
- `src/the_daddy/engine.py`
- `src/the_daddy/core/failure_recovery.py`
- `src/the_daddy/core/system_rules.json`

## What changed
- reviewer now reads recent failure signals from verification output
- reviewer now previews failure-related files so the OpenAI-backed fixer gets grounded file context
- prompt now tells the fixer to prefer targeted repair on the failing tracked file before helper churn
- rollback recovery is now capped to the last **2** recent proven workflow anchors / failed-run candidates
- engine now reads rollback lookback limits from `system_rules.json`

## Hard safety rule
The agent must never roll back beyond the last 2 recent proven workflow anchors.
This prevents freestyle deep rollback that could wipe too much good progress.
