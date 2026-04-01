# Architecture

## System intent

THEY-CALL-ME-THE-DADDY is a bounded defensive repository-maintenance system.
It is designed to:

- diagnose and repair broken repo workflows
- improve its own structure in small policy-bounded steps
- vet external agent intelligence before trust is granted
- preserve durable memory across repeated runs
- compound safe improvements over time without becoming an unrestricted shell agent

## Operational lanes

### 1. Wake review lane
The wake cycle inspects repo structure, recent memory, and key files before runtime debugging.
Its job is to detect architectural gaps, stale patterns, and missing safeguards.
It may propose small low-risk self-evolution actions.

### 2. Runtime debugging lane
The runtime lane executes the configured repo command, diagnoses failures, proposes narrow patches, applies only policy-approved changes, and reruns verification.

### 3. External vetting lane
Unknown external agent proposals are quarantined, reviewed, policy-checked, and routed through trust decisions before they influence the system.

## Safety boundaries

- High-risk or sensitive targets are not part of safe auto-apply.
- Workflow edits are not treated as low-risk self-evolution.
- Self-evolution is capped and protected by a repeated-failure circuit breaker.
- The system is intended to prefer advisory backlog growth over unsafe writes.

## Durability expectations

The long-term architecture expects the following controls to mature over time:

- durable memory with explicit schema/version handling
- drift detection against prior repo baselines
- rollback metadata before writes
- trendable observability rather than only transient traces
- stronger commit provenance so only engine-approved changes are committed

## Current gap notes

The current implementation already separates wake review, runtime diagnosis, policy routing, memory, and external vetting.
However, several durability controls are still backlog work:

- rollback artifacts are not yet a first-class write prerequisite
- repo drift signals are still limited
- memory metadata/version enforcement is still thin
- observability is mostly per-run rather than longitudinal
- workflow commit gating is broader than ideal

## Intent guardrail

If the system is uncertain, it should prefer one of the following over broader autonomous change:

1. record the issue in backlog
2. emit a low-risk documentation artifact
3. stage or reject the change by policy
4. preserve traceable memory for a later safer run
