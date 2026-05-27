# THE DADDY — FINAL AGENT DIRECTION README

## Purpose
This system is a self-repairing, self-stabilising agent first.
Its future second role is undecided. Until then, every change must improve:
- self-repair
- recovery
- rollback
- retry
- observability
- decision quality
- PR reliability

## Current hard direction
Future agents working on this system must optimise for:

1. Self-repair
2. Recovery from no-op deadlocks
3. Safe bounded patching
4. Rollback and retry behaviour
5. Memory of failed vs successful patches
6. Observability that supports repair
7. Continuous PR/merge reliability

## Non-goals right now
Do NOT prioritise:
- broad feature building
- external task systems
- speculative multi-agent expansion
- web crawling features
- coding-agent features
unless they directly improve self-repair and self-recovery.

## Rule enforcement
System behaviour is governed by:
- src/the_daddy/core/system_rules.json
- src/the_daddy/core/self_check.py

These rules require:
- no empty cycles
- force recovery under pressure
- rollback on failure
- bounded patches only
- duplicate patch avoidance

## Reviewer behaviour
If reviewer finds no grounded patch:
- do not freeze
- do not deadlock
- force a bounded recovery patch when pressure/no-patch streak thresholds are met

## Execution standard
A valid run should:
1. review
2. patch or recover
3. test
4. rollback on failure
5. open PR on success
6. merge if safe
7. learn from the outcome

## Success condition
The system is working when it can:
- keep itself alive
- fix itself
- recover itself
- avoid repeating bad patches
- continue producing safe PRs
without human intervention.


## Conflict recovery
The agent must now also handle PR merge conflicts.

If a PR is blocked by conflicts, the expected recovery loop is:
1. fetch latest `main`
2. rebase or recreate the branch
3. reapply the bounded patch
4. rerun verification
5. push a replacement branch
6. open a replacement PR

A merge conflict is not treated as a terminal failure. It is a recovery event.


## Failure-driven evolution
When a run fails, failure is treated as repair input.

Expected behaviour:
1. record the failure
2. roll back current broken patch if possible
3. re-verify after rollback
4. on the next run, inspect recent failed runs
5. restore the most recent last-known-good rollback manifest
6. if that still fails, step back further through older failed runs
7. continue the workflow after a stable base is restored
