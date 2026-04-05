# THEY-CALL-ME-THE-DADDY

Self-maintaining autonomous dev system focused on one thing first:

**survive, repair, patch safely, and keep shipping clean PRs**

---

## What this project is

THEY-CALL-ME-THE-DADDY is a bounded self-improving repository agent.

It reviews the repo, proposes a small safe patch, applies it, runs tests, opens a PR, and auto-merges when the result is safe.

This project is **not** meant to chase fake intelligence milestones, random architecture experiments, or ungrounded agent spawning.

The system exists to:

- detect failures
- recover from bad runs
- avoid deadlocks
- keep patching safely
- maintain PR flow
- learn from repeated success and failure

---

## Current direction

This repo already went through a bad drift phase where speculative “Level 2–9” logic got layered on top of the original build and pulled it away from its actual purpose.

That drift caused deadlocks, no-op cycles, broken planner behaviour, and noise.

The correct direction is now restored:

- keep the original bounded patch loop
- keep helper-lane observability improvements safe
- protect core planner/engine files from destructive mutation
- prefer real small reversible patches over speculative expansion
- do not skip phases

---

## Core operating loop

The agent should work like this:

1. Review repo state and memory
2. Propose a bounded patch
3. Apply patch safely
4. Run verification (`pytest -q`)
5. If tests pass:
   - open PR
   - auto-merge if safe
6. If tests fail:
   - rollback immediately
   - record failure pattern
   - attempt recovery next run
7. If no patch is available:
   - diagnose why
   - avoid empty deadlock cycles
   - continue improving bounded decision quality

---

## Patch rules

All patches must be:

- small
- bounded
- reversible
- testable
- non-destructive

Preferred operations:

- append
- extend
- safe regex replace

Avoid:

- large rewrites
- speculative architecture churn
- touching protected core files without a grounded reason
- duplicate or low-value patch loops

---

## Test rule

Every patch must:

- run tests
- pass before PR
- rollback immediately on failure

No exceptions.

---

## PR rule

If patch is valid:

- open PR
- include clear summary
- auto-merge if safe

If no patch is valid:

- system must explain why
- system must record the deadlock or constraint
- system must improve recovery/fallback logic over time

---

## Protected direction

A working agent that improves slowly is better than a smart-looking agent that breaks itself.

This project must always prefer:

- survival over ambition
- repair over expansion
- stability over novelty
- grounded patches over speculative behaviour

---

## Evolution phases

The agent evolves in this order only.

### Phase 1 — Repair
Focus on:

- fixing failures
- rollback reliability
- retry logic
- failure recovery

### Phase 2 — Stability
Focus on:

- eliminating deadlocks
- improving fallback decisions
- keeping PR flow alive
- preventing no-action stalls

### Phase 3 — Awareness
Focus on:

- trace summaries
- error summaries
- run-health visibility
- architecture visibility

### Phase 4 — Capability
Focus on:

- safely extending existing agents
- improving planner/reviewer quality
- strengthening bounded decision-making

### Phase 5 — Expansion
Future only.

Not active until Phases 1–4 are genuinely stable.

Examples of future work:

- web crawling
- broader coding tasks
- external task execution

---

## What this repo is NOT doing right now

This repo is not currently trying to become a free-roaming autonomous architect.

It is not prioritising:

- agent spawning for its own sake
- self-rewrite experiments
- speculative multi-layer goal systems
- synthetic evolution when grounded bounded work is still the real need

If a future change does not make the system better at surviving, patching, and recovering, it should not be implemented.

---

## Critical files

These are core to the current brain and should be treated carefully:

- `src/the_daddy/engine.py`
- `src/the_daddy/agents/reviewer.py`
- `src/the_daddy/agents/improvement_planner.py`
- `src/the_daddy/memory/repository.py`
- `src/the_daddy/core/system_rules.json`
- `src/the_daddy/core/self_check.py`
- `src/the_daddy/core/conflict_recovery.py`
- `src/the_daddy/core/failure_recovery.py`

Runtime helper lane:

- `src/the_daddy/runtime/trace_summary.py`
- `src/the_daddy/runtime/error_digest.py`
- `src/the_daddy/runtime/run_health.py`
- `src/the_daddy/runtime/reviewer_fallback.py`
- `src/the_daddy/runtime/architecture_probe.py`

---

## Current success condition

This system is considered healthy when it can:

- run continuously
- fix its own failures
- recover from bad patches
- avoid deadlocks
- produce consistent PRs
- auto-merge safe bounded patches
- learn from repeated success and failure

without needing constant human rescue.

---

## Current repo status

The restored intended behaviour is:

- bounded helper-lane improvements are allowed
- safe PR flow is restored
- auto-merge works when verification passes
- speculative “level” drift is not the main direction anymore

The current focus is to strengthen the original build path, not replace it.

---

## Rule for future agents touching this repo

Before changing anything, ask:

**Does this make the agent better at surviving and fixing itself?**

If the answer is no, do not implement it.
