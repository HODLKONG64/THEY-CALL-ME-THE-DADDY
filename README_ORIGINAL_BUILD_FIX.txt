ORIGINAL BUILD FIX PACK

This pack removes the speculative Level 3-9 additions and restores the last clean, stable build set.

Included files:
- src/the_daddy/agents/reviewer.py
- src/the_daddy/agents/improvement_planner.py
- src/the_daddy/runtime/trace_summary.py
- src/the_daddy/runtime/error_digest.py
- src/the_daddy/runtime/run_health.py
- src/the_daddy/runtime/reviewer_fallback.py
- src/the_daddy/runtime/architecture_probe.py

Intent:
- restore the stable helper-lane build
- remove speculative spawning/goal/self-rewrite layers
- get back to the original bounded PR/merge behaviour
