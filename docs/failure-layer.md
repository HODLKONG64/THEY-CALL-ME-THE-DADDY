# Failure-Driven Evolution Layer

This bundle adds rollback-first repair behaviour on top of the original stable build.

Included:
- full src/the_daddy/engine.py
- full src/the_daddy/agents/reviewer.py
- src/the_daddy/core/system_rules.json
- src/the_daddy/core/self_check.py
- src/the_daddy/core/conflict_recovery.py
- src/the_daddy/core/failure_recovery.py

Behaviour:
- rollback current broken patch on failure
- verify after rollback
- on the next run, inspect recent failed runs
- restore from the latest rollback manifest first
- if still broken, step back further through older failed runs
