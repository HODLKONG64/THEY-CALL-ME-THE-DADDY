# No-middleman SWARMSY Doctor repair workflow

## User experience

1. User tells SWARMSY: **"Ask Daddy to fix X."**
2. SWARMSY creates a structured Doctor Request (queued + archive id).
3. SWARMSY replies: **"Doctor request queued. You can leave this. I’ll track it in the repair archive."**
4. Daddy queue worker polls queued requests, runs repair flow, opens/updates PR, and archives final status.
5. User can later ask SWARMSY: **"Show me recent Daddy repairs."**

## Structured request fields

- problem summary
- repo target
- user intent
- optional feature/page hint
- optional logs/screenshots
- optional failing command
- safe allowed paths
- priority
- archive id
- status timeline (starts with `queued`)

## Worker lifecycle

- `queued -> running`
- enforce target repo allowlist (`DADDY_ALLOWED_TARGET_REPOS`)
- enforce SWARMSY external mode target (`HODLKONG64/SWARMSY` only)
- reject secret-file or out-of-scope path changes
- run repair attempt + validation
- classify review comments (`actionable_blocker`, `stale_noise`, `needs_human_approval`)
- apply fixes for actionable blockers in bounded cycles
- finalize in one terminal state (no silent waiting):
  - `merged`
  - `pr_opened_waiting_review`
  - `blocked_needs_human_permission`
  - `failed_with_reason`

## Human intervention is required only when

- review comments require explicit human approval (policy/security/credential actions)
- repo target is not allowlisted
- requested scope is unsafe/destructive
- policy override is required

## Queue poller workflow

Daddy includes `.github/workflows/swarmsy-doctor-queue.yml` as a manual operator entrypoint.

- current trigger: manual dispatch only
- scheduled/issue-label polling stays disabled until a real remote queue source is wired in
- current behavior is truthful: if no hydrated queue source is configured, the CLI reports that condition and leaves queued requests unchanged

It attempts one queued request at a time from a configured archive source and prints recent archived repairs.
