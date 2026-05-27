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

## Doctor request queue handoff (v1)

When SWARMSY needs Doctor help but Daddy is busy/no response, SWARMSY should queue a Doctor Request and continue local handling.

- Preferred v1 queue: GitHub issue in `HODLKONG64/THEY-CALL-ME-THE-DADDY`
- Required labels: `doctor-request`, `target:swarmsy`
- SWARMSY should record the request id, queue URL, and status `waiting_for_doctor`

See `docs/SWARMSY_DOCTOR_REQUEST_QUEUE.md` for schema and status transitions.

## Full handoff flow

1. SWARMSY detects a fix need.
2. SWARMSY attempts normal local/app-side repair first.
3. If Daddy is unavailable/busy, SWARMSY queues a Doctor Request.
4. Daddy self-repair flow continues independently.
5. Daddy later enters explicit SWARMSY Doctor mode (manual/scheduled/dispatch).
6. Daddy validates allowlist + target root + SWARMSY validation command + safe path scope.
7. Daddy pushes a SWARMSY branch, patches, validates, and opens a PR.
8. Daddy updates the Doctor Request with branch/PR/results and final status.

## SWARMSY auto-merge policy

- Default: **off** (`DADDY_SWARMSY_AUTO_MERGE=false`)
- Enabled only with explicit opt-in and successful SWARMSY validation
- Daddy must never silently auto-merge external repos by default
