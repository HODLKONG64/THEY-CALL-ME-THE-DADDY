# THEY-CALL-ME-THE-DADDY — Architecture

## Intent
A bounded repo maintenance system that wakes on schedule, audits itself, applies only low-risk self-evolution, diagnoses failing commands, and stores durable memory in R2.

## Lanes

### 1. Wake review lane
The reviewer inspects repo state, memory state, and key files. It must always return at least one safe self-evolution action. Safe means additive docs, tests, metadata guards, or low-risk structural notes.

### 2. Runtime repair lane
The diagnoser only acts after command failure. Runtime patching is separate from wake-review self-evolution.

### 3. External vetting lane
Unknown agents never write directly to trusted memory or code. Their proposals enter quarantine and are reviewed before any promotion.

## Commit gating
GitHub Actions only commits changes when the engine run record shows approved applied patches. Raw filesystem drift is not enough.

## Rollback metadata
Every applied patch stores rollback metadata with prior content hash and, when small enough, prior content snapshot.

## Drift
Each run records a repo fingerprint from git HEAD and hashes of key files. Reviews should be compared against this fingerprint so stale advice can be identified.
