# SWARMSY

SWARMSY is an open-source experimental app for swarm coordination, agent-assisted building, community tasks, promotion actions, and self-improving project workflows.

This repo is the app layer. It is allowed to include experimental self-evolution, architecture planning, automated PR creation, automated merge logic, and internal repair/doctor-style maintenance behaviour.

Read the locked app direction first:

- [`docs/SWARMSY_APP_DIRECTION.md`](docs/SWARMSY_APP_DIRECTION.md)

---

## What this project is

SWARMSY is a test app and open-source build system for agent-powered collaboration.

It is intended to help humans and AI agents coordinate around:

- app ideas
- user tasks
- community promotion
- feature proposals
- documentation improvements
- repo maintenance
- swarm-style collaboration
- live project improvement

This is not a normal static app repo. The automation layer is part of the experiment.

---

## Intentional experimental features

Do not remove these just because they look risky in a normal production app:

- self-evolution lane
- architecture lane
- auto-PR logic
- auto-merge logic
- internal repair/doctor behaviour
- agent-led maintenance
- test-app autonomy

These are part of the purpose of SWARMSY.

The goal is not to make the app passive. The goal is to test a living app that can document, review, repair, and improve itself with clear guardrails.

---

## Product role

SWARMSY should become the app-facing swarm system.

The app should focus on:

- community coordination
- live build feedback
- contributor workflows
- app improvement tasks
- promotion missions
- swarm ideas
- agent-assisted issue handling
- public-facing product direction

---

## Internal agent role

The repo may contain a built-in doctor/repair concept.

That doctor layer should be treated as an internal maintenance agent inside the SWARMSY app system, not as a separate product identity that takes over the app.

Recommended naming:

- **SWARMSY** = app, product, community, swarm layer
- **Doctor** = internal repair and maintenance layer
- **Agent** = task runner, reviewer, planner, or fixer
- **Contributor** = human or AI helper submitting improvements

---

## Guardrails

Even as a test app, SWARMSY should avoid accidental damage.

Required guardrails:

- no accidental cross-repo writes
- no secret logging
- no API key/token storage in memory
- no destructive shell commands
- no silent failed deploys
- visible audit trail for automated actions
- rollback notes for every automated patch
- clear target repo naming when automation writes to GitHub

---

## Patch rules

All automated patches should be:

- small
- bounded
- reversible
- testable
- non-destructive

Preferred operations:

- append
- extend
- safe regex replace
- targeted file update

Avoid:

- large rewrites without a clear reason
- unrelated cleanup bundled into feature work
- fake heartbeat/no-op patches
- product drift away from SWARMSY
- changing protected core files without grounded evidence

---

## Test rule

Every meaningful patch should run the relevant verification command before being treated as successful.

The current default verification path is Python test based:

```bash
pytest -q
```

If the app later adds web/mobile/frontend tooling, document the extra commands here rather than hiding them in agent memory.

---

## PR rule

If a patch is valid:

- open a clear PR or commit directly only when explicitly requested
- include a clear summary
- include verification details
- auto-merge only when the configured safety rules allow it

If no patch is valid:

- explain why
- record the blocker
- avoid empty deadlock cycles
- improve the next-run decision path

---

## Learning and memory

The app/agent system may keep compact operational memory so it can learn from repeated success and failure.

Memory should store:

- run mode
- outcome
- subsystem
- root cause
- changed paths
- tests run
- blocker reasons
- next-best action
- avoid-next-time lessons

Memory must not store:

- secrets
- API keys
- tokens
- full environment dumps
- unnecessary full file contents

---

## Current success condition

SWARMSY is healthy when it can:

- keep app direction visible
- accept useful community/app changes
- run safe automated maintenance
- recover from failed patches
- avoid deadlocks
- keep PR flow readable
- preserve clear audit trails
- improve without drifting away from the app mission

---

## Rule for future agents touching this repo

Before changing anything, ask:

**Does this make the SWARMSY app better as an open-source swarm coordination and agent-powered build system?**

If yes, proceed carefully.

If no, do not add noise.
