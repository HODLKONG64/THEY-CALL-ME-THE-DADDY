CONFLICT SELF-HEALING UPGRADE

This pack builds on the original build with self-check complete.

Added:
- src/the_daddy/core/conflict_recovery.py
- system_rules.json updated with recover_on_merge_conflict
- reviewer.py updated with conflict recovery guidance and execution notes

Purpose:
- when a PR is blocked by merge conflicts, treat it as a recoverable event
- fetch latest main
- reapply the bounded patch
- rerun tests
- open a replacement PR
