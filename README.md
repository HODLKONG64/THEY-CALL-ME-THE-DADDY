# THEY-CALL-ME-THE-DADDY

A bounded self-maintenance and repo-improvement agent that can review its own repo state, propose tightly-scoped changes, verify them, remember what happened, and grow safely over time.

---

## What this repo is

This project is no longer just a simple debug runner.

It now sits between two modes of operation:

1. **Bounded maintenance**
   - wake up
   - inspect repo state
   - review architecture and drift
   - propose small self-evolution actions
   - score and risk-classify those actions
   - apply only safe bounded patches
   - verify by running the configured command
   - save memory, metrics, traces, failure patterns, and learning lessons

2. **Controlled capability growth**
   - restore older missing infrastructure where useful
   - keep stronger newer safety rules
   - expand into observability, vetting, telemetry, dashboarding, and reputation systems
   - allow the agent to get stronger without letting it become reckless

This repo should grow muscles, not lose its brain.

---

## Current live direction

The current working spine of the repo is the newer bounded-maintenance path.

That means the repo should keep and build around:

- `src/the_daddy/cli.py`
- `src/the_daddy/engine.py`
- `src/the_daddy/agents/reviewer.py`
- `src/the_daddy/runtime/file_tools.py`
- `src/the_daddy/runtime/command_runner.py`
- `src/the_daddy/policy.py`
- `src/the_daddy/scoring.py`
- `src/the_daddy/merge_rules.py`
- `src/the_daddy/git_tools.py`
- `src/the_daddy/models.py`
- `src/the_daddy/runtime/learning_journal.py`

These files define the current maintenance loop, scoring logic, PR delivery path, learning journal flow, protected-core handling, and bounded self-evolution rules.

---

## Core runtime flow

1. Load settings and durable memory
2. Snapshot repo state
3. Run wake reviewer
4. Choose operating mode
5. Collect self-evolution actions
6. Score the patch set
7. Apply policy checks
8. Apply only safe patches
9. Run verification command
10. Save:
   - run record
   - trace
   - metrics
   - failure patterns
   - learning journal
11. If GitHub is configured and verification passes:
   - prepare branch
   - commit current changes
   - open PR
   - auto-merge only when rules allow it

---

## Protected-core rule

These files are protected from direct blunt auto-patching in the safe lane:

- `src/the_daddy/agents/reviewer.py`
- `src/the_daddy/engine.py`
- `src/the_daddy/models.py`
- `src/the_daddy/policy.py`
- `src/the_daddy/scoring.py`
- `src/the_daddy/merge_rules.py`
- `src/the_daddy/git_tools.py`
- `src/the_daddy/runtime/command_runner.py`

The agent can inspect them, reason about them, and propose branch-lane or human-reviewed work around them, but it should not silently hammer them in the normal safe loop.

---

## Runtime helper lane

The current bounded helper lane should include these allowlisted helper files:

- `src/the_daddy/runtime/trace_summary.py`
- `src/the_daddy/runtime/reviewer_fallback.py`
- `src/the_daddy/runtime/architecture_probe.py`
- `src/the_daddy/runtime/error_digest.py`
- `src/the_daddy/runtime/run_health.py`

These helpers are useful because they let the system expand observability and health awareness without ripping through protected core logic.

---

## Durable memory and learning

The system should persist and use:

- architecture reviews
- run history
- backlog
- failure patterns
- metrics ledger
- patch provenance
- learning weights
- learning journal
- reputation data where enabled

The memory layer must remain durable and compatible with older states.

Important hardening already added:
- older `failure_patterns` entries that are missing `signature` should be backfilled on load instead of crashing the repo
- learning journal entries should be written after runs so the agent remembers what worked, what failed, and what targets should cool down

---

## Added updates needed

This section is the real upgrade map.

### 1. Keep the newer bounded-maintenance core

Keep the newer versions of:

- `src/the_daddy/cli.py`
- `src/the_daddy/engine.py`
- `src/the_daddy/agents/reviewer.py`
- `src/the_daddy/runtime/file_tools.py`
- `src/the_daddy/runtime/command_runner.py`
- `src/the_daddy/policy.py`
- `src/the_daddy/scoring.py`
- `src/the_daddy/merge_rules.py`
- `src/the_daddy/git_tools.py`
- `src/the_daddy/models.py`
- `src/the_daddy/runtime/learning_journal.py`

These are the backbone of the current system and should not be rolled back to weaker older versions.

### 2. Restore missing old infrastructure files

Restore these old files from the recovered main tree if they are missing:

- `src/the_daddy/config.py`
- `src/the_daddy/memory/r2_store.py`
- `src/the_daddy/memory/repository.py`
- `src/the_daddy/agents/openai_client.py`
- `src/the_daddy/agents/diagnoser.py`
- `src/the_daddy/agents/improvement_planner.py`

These are still needed because they are real infrastructure, not fluff.

### 3. Restore broader capability files where wanted

Bring these back if the goal is a stronger multi-surface agent:

- `src/the_daddy/agents/vetter.py`
- `src/the_daddy/external/reputation.py`
- `src/the_daddy/dashboard.py`
- `src/the_daddy/prompts.py`
- `src/the_daddy/telemetry.py`
- `src/the_daddy/web/schemas.py`
- `src/the_daddy/logging_utils.py`

These are not fake by default. They are part of the older wider system and can make the agent more capable.

### 4. Re-add growth features without deleting new safeguards

The repo should support growth, but through lanes.

That means:

- safe lane for bounded auto-patches
- branch lane for riskier or broader work
- architecture lane for structure-level changes
- optional manual / non-default test lane for aggressive growth experiments

The new anti-loop reviewer rules should stay alive in the safe lane.

### 5. Keep newer anti-drift reviewer rules

The reviewer should still:
- block fake or hallucinated near-miss paths
- suppress repetitive low-value wake-review churn
- avoid blindly reusing blocked targets immediately
- prefer allowlisted runtime helper files first
- avoid replacing existing runtime helpers with blunt `replace_file` when that is unsafe
- suppress junk doc churn when no valid code action exists

These rules stop the agent from getting stuck in weak loops.

### 6. Keep the growth mindset anyway

Even with those rules, the repo should still allow:

- richer logging
- broader telemetry
- stronger diagnostics
- vetting of outside proposals
- reputation handling
- more memory-backed learning
- stronger architecture reviews
- more branch-lane experiments
- more explicit test coverage where it actually matters

The goal is not to make the agent timid.
The goal is to make it dangerous in the right direction.

---

## Files to restore now

If doing a direct recovery pass, these should be restored first:

- `src/the_daddy/config.py`
- `src/the_daddy/memory/r2_store.py`
- `src/the_daddy/memory/repository.py`
- `src/the_daddy/agents/openai_client.py`
- `src/the_daddy/agents/diagnoser.py`
- `src/the_daddy/agents/improvement_planner.py`
- `src/the_daddy/agents/vetter.py`
- `src/the_daddy/external/reputation.py`
- `src/the_daddy/dashboard.py`
- `src/the_daddy/prompts.py`
- `src/the_daddy/telemetry.py`
- `src/the_daddy/web/schemas.py`
- `src/the_daddy/logging_utils.py`

---

## Files to keep newer

Do not replace the current stronger versions of:

- `src/the_daddy/agents/reviewer.py`
- `src/the_daddy/engine.py`
- `src/the_daddy/policy.py`
- `src/the_daddy/models.py`
- `src/the_daddy/scoring.py`
- `src/the_daddy/merge_rules.py`
- `src/the_daddy/git_tools.py`
- `src/the_daddy/runtime/file_tools.py`
- `src/the_daddy/runtime/command_runner.py`
- `src/the_daddy/cli.py`

If these need changes, merge forward into the newer versions. Do not downgrade them.

---

## Tests and growth policy

Older repetitive wake-review / self-evolution test loops should not be the default wake-cycle path.

If you want those back, the better structure is:

- keep them as manual tests
- or put them in branch-only verification
- or use them as architecture-lane confidence checks

That lets the repo train harder without stuffing the safe lane with repetitive nonsense.

---

## Logging and observability policy

`logging_utils.py` can come back if you want the repo bigger and stronger.

But it should be wired cleanly.

It should not become:
- a fake drift target
- a generic dump file
- a replacement for the bounded helper lane

Use it as a real utility, not as an excuse for the reviewer to invent random helper churn.

---

## Recommended merge order

1. restore missing infrastructure files
2. restore optional broad-capability files
3. keep newer bounded core files
4. keep improved `policy.py`
5. keep improved `models.py`
6. keep newer reviewer logic
7. keep learning journal flow
8. update README to reflect the true architecture
9. run verification
10. then decide what branch-lane growth work comes next

---

## Verification command

Typical verification remains:

```bash
python -m src.the_daddy.cli run
```

If settings point at tests, the command runner should still capture:

- return code
- stdout
- stderr
- timeout
- duration
- combined output

---

## Repo philosophy

This repo should become:

- harder to break
- better at learning
- better at remembering
- better at reviewing itself
- broader in capability
- stricter in the safe lane
- more experimental in branch and architecture lanes

That is how it gets muscles.

---

## Short version

Restore the old missing infrastructure.
Keep the newer stronger core.
Bring back broader capability files.
Do not throw away the newer safeguards.
Grow the system by lane, not by chaos.
