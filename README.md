# THEY-CALL-ME-THE-DADDY

THEY-CALL-ME-THE-DADDY ("Daddy") is the Doctor/self-repair engine repo.

It is **not** the SWARMSY app or product runtime.

- **Daddy** = Doctor engine, repair layer, self-maintaining automation
- **SWARMSY** = separate app/product runtime with its own repo and product docs
- Daddy may later repair SWARMSY by opening PRs, but only when the target repo is explicitly configured and allowlisted

Start here:

- [`docs/SWARMSY_DOCTOR_BRIDGE.md`](docs/SWARMSY_DOCTOR_BRIDGE.md)
- [`docs/TARGET_REPO_SAFETY_CONTRACT.md`](docs/TARGET_REPO_SAFETY_CONTRACT.md)

## What this repo does

Daddy is the engine layer for:

- self-evolution
- architecture planning
- bounded patch generation
- automated PR creation
- automated merge decisions
- internal repair and recovery loops
- run memory and audit trails

Those capabilities belong to the Doctor engine. They should not be described as proof that this repo is the SWARMSY app layer.

## Operating modes

### Self-repair mode

Self-repair mode targets Daddy itself.

- default target repo: `HODLKONG64/THEY-CALL-ME-THE-DADDY`
- default target root: this checked-out Daddy repo
- default allowlist: `HODLKONG64/THEY-CALL-ME-THE-DADDY`

This is the safe default for continuous repair, auto-PR, and auto-merge behavior.

### External Doctor mode

Daddy can later act as a Doctor layer for another repo such as SWARMSY, but only with explicit target-repo configuration.

External mode requires all of the following:

- `GITHUB_REPO` set to the target repo, for example `HODLKONG64/SWARMSY`
- `DADDY_TARGET_ROOT` set to an actual checked-out copy of that target repo
- `DADDY_COMMAND` / validation commands set to the correct verification command for that target repo
- `DADDY_ALLOWED_TARGET_REPOS` updated to include that target repo

Until then, Daddy should treat SWARMSY support as planned bridge work, not as an already-enabled runtime path.

## Guardrails

- no cross-repo writes unless the target repo is allowlisted
- PR creation and PR merge are blocked for non-allowlisted repos
- auto-merge remains a Doctor-engine capability, not a product-app claim
- validation must run against the currently configured target repo
- audit trails should clearly show which repo the Doctor is acting on

## Success condition

Daddy is healthy when it can:

- repair itself safely
- produce bounded, reviewable patches
- open clear PRs for allowed targets
- merge only when configured safety rules allow it
- stay distinct from SWARMSY product identity
- avoid accidental cross-repo confusion
