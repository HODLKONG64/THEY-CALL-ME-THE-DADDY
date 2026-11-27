# Doctor repair intelligence

The existing Brain-approved website repair flow, CI labels, Codex review, test isolation,
owner approvals and branch protections remain authoritative. This feature is **advisory
memory**, not a second repair queue or permission system. It must not authorize a merge.

## What is stored

- Existing JSON archive: all local repair requests and checkpoints, replayable edits,
  validation and delivery evidence. Exact replay now requires a recorded head and merge
  SHA, no known failed/pending post-merge validation/deployment, and current path scope.
  Exact anchors and the existing validator/API approval are still required.
- `<archive basename>.history.sqlite3`: private, restartable index of sanitized GitHub
  issue/PR titles, descriptions, state and update times. A related closed item is not a
  proven fix. Selected PRs are checked for actual merge state and enriched with file names,
  reviews and comments. Similarity is lexical, not embedding-based. Related failures
  provide cautionary evidence, never direct replay.
- Optional dedicated private R2 bucket: immutable content-addressed terminal lesson
  summaries only. No active jobs, raw logs, credentials or executable edits. Both Doctors
  can import the same advisory lessons, and local replay still uses the local archive.
  This is not a backup of the full queue.

## Enable GitHub indexing

Add to the protected service environment, never Git:

```sh
DADDY_DOCTOR_HISTORY_ENABLED=true
# Optional additional read-only scope; current target is always included.
DADDY_DOCTOR_HISTORY_REPOS=HODLKONG64/THEY-CALL-ME-THE-DADDY,Crypto-Moonboys/Crypto-Moonboys.github.io,HODLKONG64/the-brain,HODLKONG64/diz-iz-it,HODLKONG64/HAY-MUM-IM-BUILDING-AGENTS-OF-CHANGE,Crypto-Moonboys/SWARMSY-Ai
```

Only list repositories that the operator has authorized for technical learning and that
the worker's token can read. Additional read scope does not grant write access.
For cross-repository history, the token needs appropriate issue/PR read permissions.
Keep the archive and index on a service-private filesystem.

```sh
python -m the_daddy.swarmsy_doctor_queue --sync-history
```

Each call indexes one page of up to 100 records per configured repository. It commits
the checkpoint only with a successful page, revisits an overlapping updated-time window,
and starts a full reconciliation every 30 days. Schedule repeated calls with a separate
systemd timer (for example, every five minutes). Backfill is complete only after every
repository reports `cycle_complete: true`; the initial run is not a complete backfill.
The API fetches related PR metadata on demand, not every historical diff/review.
Deleted or inaccessible records require operator reconciliation; the index is advisory.

## Share private terminal lessons

Create a **dedicated private R2 bucket**, distinct from the legacy memory bucket; disable
public access and give each approved host bucket-scoped credentials. Do not point this
at public Brain/Wiki storage. Confirm your retention and access policies first.

```sh
DADDY_DOCTOR_INTELLIGENCE_BUCKET=your-private-doctor-intelligence-bucket
DADDY_DOCTOR_INTELLIGENCE_R2_ACCESS_KEY_ID=...
DADDY_DOCTOR_INTELLIGENCE_R2_SECRET_ACCESS_KEY=...
# R2_ENDPOINT_URL must be the HTTPS account S3 endpoint.
```

Use the same dedicated bucket and the authorized read repository list on both hosts.
Run with the configured target and existing local queue:

```sh
python -m the_daddy.swarmsy_doctor_queue --sync-shared-memory
```

Each invocation exports up to 25 new terminal versions from its configured target and
imports up to 25 objects per read repository. The import cursor wraps to find late
inserts. Sync checkpoints and cached lessons are scoped to the R2 account endpoint
and bucket. Switching either starts an independent sync and republishes the local
terminal lessons; credentials can rotate without resetting progress. Older unscoped
cache tables are ignored. Failures return a nonzero status; the local queue remains intact. Shared
records are checked for schema, size, repository and content hash and sanitized again.
A record's hash proves consistency, not the truth of its claims. Remote lessons are
untrusted advisory evidence and never execute edits. Use a dedicated sync timer; do not
put remote synchronization inside the repair process lock. Monitor sync failures and
bucket growth. Storage is append-only by convention, not a cloud-enforced WORM policy.

## Deployment and failover gates

Use the same-host supervisor and archive lock already documented in
[Doctor Two](https://github.com/HODLKONG64/diz-iz-it). Upgrade primary and pinned
standby only after CI, then test the standby with the queue format and shared bucket.
A separate VPS can run the history synchronization/read-only index. Do **not** run a
second active repair watcher for the same target on another host yet: R2 lesson
replication is not a distributed lease or queue, and the local file lock cannot fence
another machine. The existing Brain FIX approval remains mandatory.

## Acceptance and next phase

- Run the complete Doctor CI and the two-host mocked R2 tests.
- Verify local matching, failed-repair evidence, paginated GitHub backfill, and a real
  private R2 sync on both hosts. Confirm that a failed deployment is not reused.
- Verify the indexed repo permissions and exact production endpoint after a real fix.
- A cross-host fenced execution lease and durable Brain case queue, deduplicated
  automatic issue creation/closure, SAM technical intake, full review/diff/CI evidence
  ingestion, semantic embeddings, live smoke probes, and cost/recurrence dashboards
  remain separate work. They must not bypass the current review/approval gates.


## Independent sharing scope and diagnostics

Set `DADDY_DOCTOR_SHARED_REPOS` to the comma-separated repositories explicitly
approved for private advisory memory retrieval. If unset, the existing GitHub
history scope is used. An explicitly empty value means only the configured target.
The GitHub history scope and repair write allowlist remain independent.
For the website worker, keep the GitHub read scope limited to its authorized
repositories and configure the wider shared scope only if those lessons are
approved for that service. A shared bucket credential is not an IAM restriction
per repository; this setting controls application retrieval, not bucket permissions.

Use the service's existing environment and archive to run:

```sh
python -m the_daddy.swarmsy_doctor_queue --intelligence-report
```

The report counts unique indexed records, reports scan checkpoints, repair outcomes,
post-merge CI and deployment-job outcomes, repeated normalized problem groups and
median case age at last update. It does not expose raw support reports or estimate API
costs. Repeated groups are lexical indicators, not proven root causes. Merge fraction
is not production success. Case age is not active compute time.

Related merged PR retrieval now includes bounded redacted patch excerpts, inline
review notes and available head/merge SHA provenance. This does not bulk ingest every
diff, and no historical patch is automatically executed. Existing approval and
validation requirements remain unchanged.

After reviewed CI passes, upgrade the two active Python installations and the pinned
standby using the established rollout process; restart the active watchers so they
read the new scope. No D1 migration or new R2 bucket is necessary.


## Distilled repair knowledge (version 1)

Doctor's historical repair context uses an additive local SQLite table, `distilled_history`.
Existing archives, the raw history index, R2 terminal lessons and GitHub records remain intact.

The existing `--sync-history` command processes up to five pending records per successfully
indexed repository per run. Each record is keyed by repository, PR/issue number, source
revision and distillation version. Unchanged records are cached for 30 days; a changed
source revision invalidates the previous evidence immediately. Failed enrichment retains
unverified metadata, waits one hour before retrying that revision and stops further
enrichment for the repository during that run. The initial metadata index keeps progressing.

Distillation is deterministic and extractive, with no additional OpenAI calls. It removes
routine review requests, acknowledgement chatter, duplicate lines and markup; classifies
technical, art-only-candidate and uncertain records; and extracts explicitly reported
problem, cause, solution, failure and verification statements. Art-only candidates and
uncertain records are not deleted. Only technical candidates trigger bounded GitHub
enrichment: merge identity, changed paths, selected technical discussion/review excerpts,
and observed check conclusions on the exact merge SHA. Missing data remains unknown.
Reported root causes and fixes are claims, not independent verification. No raw patches
are sent by the historical retrieval path.

During repairs, Doctor ranks local distilled evidence, with metadata-only fallback when
a record is new or stale. It does not refetch historical discussions. The combined
local/archive, R2 terminal lessons and historical advisory context is deduplicated and
limited to at most five records and 7,200 serialized JSON bytes. This cap is not a cap
on the entire repair prompt or a token-count guarantee. Existing exact replay, scope,
validation, Codex and merge requirements are unchanged.

Run the report under the same protected environment as the existing sync service:

```sh
python -m the_daddy.swarmsy_doctor_queue --distillation-report
```

The report shows unique indexed records, current distilled records, stale revisions,
pending/retry counts, classification counts and source/stored bytes. Byte counts
compare bounded source metadata with stored enriched records, so enrichment can
sometimes increase stored size; they are not an estimate of API billing or token savings.

No D1 migrations, Worker releases, new credentials or bucket changes are required.
After CI/review and merging, reinstall the active runtimes and restart the watchers.
The existing timers automatically invoke the distillation stage. Keep the separately
tested recovery pin until the updated primary is verified. Do not remove historical
data or run a second repair watcher.

Limitations: this version uses lexical matching and local per-worker distilled history.
Existing R2 terminal lessons remain shared and are compacted when retrieved, but
publication of distilled GitHub records to R2, semantic embeddings, cross-source
contradiction analysis and automatic detection of superseded fixes across different
PRs require further implementation. The sample of GitHub checks is not a complete CI
attestation or production smoke test.
