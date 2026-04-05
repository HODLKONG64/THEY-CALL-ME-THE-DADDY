# Failure-Driven Evolution Layer

This pack builds on the working self-check + conflict-recovery base and adds rollback-first repair behaviour.

## Added
- `src/the_daddy/core/failure_recovery.py`
- updated `src/the_daddy/core/system_rules.json`
- added full `src/the_daddy/engine.py`

## What it does
- on the next run after a failed run, inspect recent failed runs
- restore from the latest rollback manifest and verify
- if that restore still fails, try older failed runs (up to 3)
- when the current run fails after applying a patch, roll back current changes immediately and re-verify

## Goal
Keep the agent alive, recover from bad patches, and continue the workflow instead of compounding failures.
