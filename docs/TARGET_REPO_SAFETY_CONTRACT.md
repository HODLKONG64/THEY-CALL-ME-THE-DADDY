# Target Repo Safety Contract

Daddy must always know which repo it is repairing before it writes, opens a PR, or merges a PR.

## Default self-repair mode

The default mode targets Daddy only.

- `GITHUB_REPO=HODLKONG64/THEY-CALL-ME-THE-DADDY`
- `DADDY_TARGET_ROOT` points at the checked-out Daddy repo
- `DADDY_COMMAND` uses the Daddy validation command
- `DADDY_ALLOWED_TARGET_REPOS=HODLKONG64/THEY-CALL-ME-THE-DADDY`

This is the only allowlisted target by default.

## External Doctor mode

External Doctor mode is disabled until the target repo is explicitly configured.

For a future SWARMSY target, all of the following must be set:

- `GITHUB_REPO=HODLKONG64/SWARMSY`
- `DADDY_TARGET_ROOT=/absolute/path/to/checked-out/SWARMSY`
- `DADDY_COMMAND=<SWARMSY validation command>`
- `DADDY_MAINTENANCE_COMMAND=<SWARMSY maintenance validation command>`
- `DADDY_ALLOWED_TARGET_REPOS=HODLKONG64/THEY-CALL-ME-THE-DADDY,HODLKONG64/SWARMSY`

If SWARMSY is not in the allowlist, Daddy must not create or merge SWARMSY PRs.

## Enforcement

- no cross-repo writes unless the target repo is allowlisted
- PR creation is blocked when `GITHUB_REPO` is not in `DADDY_ALLOWED_TARGET_REPOS`
- PR merge is blocked when `GITHUB_REPO` is not in `DADDY_ALLOWED_TARGET_REPOS`
- adding a repo to the allowlist is an explicit opt-in, not an automatic discovery step

This contract keeps self-repair mode scoped to Daddy and prevents SWARMSY/Daddy repo confusion.
