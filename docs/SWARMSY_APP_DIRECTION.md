# SWARMSY App Direction

SWARMSY is the app layer.

This repo is not dependent on the old Daddy repo direction. The app should carry its own product documentation, its own build direction, and its own agent-facing operating rules.

## Current position

SWARMSY is a test app and open-source experimental build.

The system is allowed to explore:

- self-evolution
- architecture planning
- automated PR creation
- automated merge logic
- agent-led maintenance
- app-level swarm behaviour
- community-editable improvement loops

These are intentional features, not blockers.

## Product role

SWARMSY should become the app-facing swarm system.

The app should focus on:

- user tasks
- community coordination
- app ideas
- promotion actions
- build suggestions
- live project improvement
- swarm-style collaboration
- AI-assisted contribution workflows

## Agent role

The app can contain a built-in doctor/repair concept, but the app should not rely on a separate Daddy repo as the product identity.

If a doctor layer exists, it should be documented as an internal maintenance agent inside the SWARMSY app system.

Recommended naming:

- SWARMSY = app/product/community layer
- Doctor = internal repair and maintenance layer
- Agent = task runner / reviewer / planner
- Contributor = human or AI helper submitting improvements

## Open-source direction

The app should be structured so the community can:

- read the roadmap
- understand the architecture
- submit ideas
- improve docs
- propose app features
- contribute UI and workflow changes
- help test swarm tasks

The repo should make it clear which parts are experimental and which parts are stable.

## What should stay

Do not remove these just because they look risky in a normal production app:

- self-evolution lane
- architecture lane
- auto-PR logic
- auto-merge logic
- experimental agent behaviour
- test-app autonomy

They are part of the purpose of this repo.

## What should be guarded

Even in a test app, the system should still avoid accidental damage.

Guardrails should include:

- clear target repo naming
- no accidental cross-repo writes
- no secret logging
- no token storage in memory
- no destructive shell commands
- no silent failed deploys
- visible audit trail for agent actions
- rollback notes for every automated patch

## Immediate documentation goal

Before more code changes, SWARMSY needs clear app docs explaining:

1. what the app is
2. what the agent is allowed to do
3. what the community can edit
4. what parts are experimental
5. how the repair/doctor layer fits into the app
6. how future agents should avoid product drift

## Rule for future agents

Do not treat SWARMSY as a generic copied repo.

Before changing anything, ask:

Does this make the SWARMSY app better as an open-source swarm coordination and agent-powered build system?

If yes, proceed carefully.

If no, do not add noise.
