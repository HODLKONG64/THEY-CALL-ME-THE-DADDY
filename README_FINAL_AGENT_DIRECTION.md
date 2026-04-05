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
