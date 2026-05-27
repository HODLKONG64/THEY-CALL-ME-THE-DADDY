# SWARMSY Doctor Bridge

SWARMSY is expected to have its own app repo and its own product-facing documentation.

THEY-CALL-ME-THE-DADDY is the Doctor engine that may later repair SWARMSY, but it is not the SWARMSY app runtime.

## Bridge status

The SWARMSY Doctor bridge is planned.

Until SWARMSY is stable, the bridge should stay dry-run-first and explicitly configured case by case.

## Relationship

- **SWARMSY** owns app behavior, product direction, and runtime concerns
- **Daddy** owns repair loops, bounded patching, PR generation, and merge safety
- Daddy may act on SWARMSY only as an external Doctor layer

## Activation rules

No automatic SWARMSY writes or merges are allowed unless they are explicitly enabled.

That means:

- `GITHUB_REPO` must point to `HODLKONG64/SWARMSY`
- `DADDY_TARGET_ROOT` must point to a checked-out SWARMSY repo
- the SWARMSY validation command must replace the Daddy default test command
- `DADDY_ALLOWED_TARGET_REPOS` must explicitly include `HODLKONG64/SWARMSY`

If any of those steps are missing, Daddy should remain in Daddy-only self-repair mode.

## Expected rollout

1. keep Daddy self-repair focused on this repo
2. keep SWARMSY product docs in the SWARMSY repo
3. enable SWARMSY Doctor mode only after explicit allowlisting
4. prefer dry runs before any automatic SWARMSY PR or merge path
