# THEY-CALL-ME-THE-DADDY

Self-maintaining autonomous dev system focused on one thing first:

**survive, repair, patch safely, and keep shipping clean PRs**

---

## What this project is

THEY-CALL-ME-THE-DADDY is a bounded self-improving repository agent.

It reviews the repo, proposes a small safe patch, applies it, runs tests, opens a PR, and auto-merges when the result is safe.

This project is **not** meant to chase fake intelligence milestones or speculative architecture experiments.

---

## Core Loop

1. Review repo + memory
2. Propose bounded patch
3. Apply patch
4. Run tests
5. If pass → PR + merge
6. If fail → rollback + learn
7. If no patch → diagnose (never stall silently)

---

## Rules

- Patches must be small, safe, reversible
- Prefer append/extend over rewrite
- Never break tests
- Never stall under pressure
- Always prefer survival over expansion

---

## Phases

1. Repair
2. Stability
3. Awareness
4. Capability
5. Expansion (future only)

---

## Current Focus

Fix deadlocks.
Maintain PR flow.
Improve decisions.

NOT:
- agent spam
- fake evolution
- speculative rewrites

---

## Success =

System runs, patches, merges, and recovers without human intervention.
