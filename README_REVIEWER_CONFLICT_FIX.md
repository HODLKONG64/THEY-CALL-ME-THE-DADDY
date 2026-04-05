# Reviewer conflict fix pack

This pack fixes the exact build break from the latest run:
- `IndentationError` in `src/the_daddy/agents/reviewer.py`

Included:
- full `src/the_daddy/agents/reviewer.py`
- `src/the_daddy/core/conflict_recovery.py`
- updated `src/the_daddy/core/system_rules.json`

Scope:
- syntax-safe conflict recovery helper wiring
- no speculative engine rewrite
- keeps the original stable build base
