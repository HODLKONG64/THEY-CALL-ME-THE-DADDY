# THEY CALL ME THE DADDY

Doctor repairs ordinary software failures in an allowlisted GitHub repository. It keeps a local repair archive, reuses verified fixes, tests proposed edits, and asks Codex to review each published commit.

## Run Doctor

Install Python 3.11+ and the project on a Linux host with Docker. Copy [.env.example](.env.example) to `.env` and configure the API credentials, GitHub repository, validation image and test command.

```bash
python -m pip install -e .
python -m the_daddy.swarmsy_doctor_queue --enqueue 'Fix the upload regression' --allow-path src/ --allow-path tests/
python -m the_daddy.swarmsy_doctor_queue --watch
```

Use `--process-once` to process one queue entry or check one pending PR. Use `--show-recent` to see repair status, PR links and the reason for any block. The [Doctor runbook](docs/SWARMSY_DOCTOR_NO_MIDDLEMAN.md) has the full setup and recovery details.

## Target repositories and merging

- `DADDY_ALLOWED_TARGET_REPOS` defaults to `HODLKONG64/THEY-CALL-ME-THE-DADDY`. Set `GITHUB_REPO` to the target and explicitly allowlist SWARMSY to repair it.
- For the VPS rollout, every Doctor-managed merge requires owner approval in the private `@WIKICOMSBOT` chat. **Approve merge** binds approval to the repository, PR, reviewed head and validated base. Doctor rechecks the decision, completed Codex review, configured CI and GitHub merge rules before merging. Protected paths may still require a manual merge.
- **Request further fix** returns the repair to review and invalidates the prior approval. **Reject** blocks the managed merge. A revised head needs fresh review, CI and owner approval. See [the rollout and remaining checks](https://github.com/HODLKONG64/THEY-CALL-ME-THE-DADDY/issues/113).
- `DADDY_SWARMSY_AUTO_MERGE` defaults to `false`. SWARMSY requests still get tested, published and reviewed in this mode.
- For configured Cloudflare Workers, the [deployment workflow and tracking setup](docs/SWARMSY_DOCTOR_NO_MIDDLEMAN.md#cloudflare-worker-deployment) can ship and verify a reviewed merge.
- The legacy `the_daddy.cli` engine remains available for diagnostics and manual PR review. The queue worker handles automatic review follow-up and merge.

### VPS validation and repair providers

The primary VPS Doctor uses isolated rootless Docker validation. The primary supervisor has opt-in local Qwen3 (`qwen3:4b-instruct`) and Codex fallback enabled. If the API review is unavailable, a candidate that passed local validation can be published for independent Codex review. A pending Codex edit blocks merging the current head. Accepted edits must match the current reviewed commit and pass validation again. The website worker uses its existing provider configuration.

[PR #119](https://github.com/HODLKONG64/THEY-CALL-ME-THE-DADDY/pull/119) verified a real Doctor self-repair through exact-head Codex review, Telegram approval, and a merge into `main`. The fix gives an empty traceback excerpt for zero or negative limits and preserves positive-limit behavior. [Doctor CI passed on merge commit `d6a7677`](https://github.com/HODLKONG64/THEY-CALL-ME-THE-DADDY/actions/runs/46100479230).

## Codex CLI repair fallback

Set both `DADDY_DOCTOR_CODEX_FALLBACK=true` and `DADDY_DOCTOR_CODEX_CLI_FALLBACK=true` to use the authenticated Codex CLI when Doctor's OpenAI repair client is unavailable and an existing PR has actionable findings. Check `codex login status` as the Doctor service account before enabling it. The CLI runs in an empty directory with shell tools disabled and receives only redacted findings, validation output and scoped source snippets. Doctor checks the proposal against the exact PR head, applies it in the isolated checkout, and validates it. Every revised head still needs fresh Codex review, required CI and exact-commit Telegram approval.

The CLI needs its own working OpenAI connection and writable Codex state directory. A CLI failure leaves the repair blocked for owner review. Requests already waiting on a legacy GitHub patch comment stay parked. Keep the CLI flag off until the isolated outage test passes on that host.

## Website support and CI tracking

The Brain sends approved website repair cases to the website-scoped Doctor service. Doctor reproduces the failure, tests the repair in isolation and requests Codex review. The owner can approve the exact reviewed commit in `@WIKICOMSBOT`. [Website support setup](https://github.com/HODLKONG64/the-brain/blob/main/support-ops/README.md)

Use `--scan-prs` for a read-only CI inventory. `DADDY_DOCTOR_WATCH_CI=true` enables ongoing tracking. `DADDY_DOCTOR_DISPATCH_CI=true` lets Doctor request missing checks for tracked commits with a website-scoped token that has Actions write access. Doctor can adopt an eligible functional failure tagged `doctor:repair-ci` after reproducing it. `doctor:merge-ci` enables the separate CI merge path after Codex and required GitHub checks pass. Doctor records post-merge checks against the merge SHA and can queue one scoped follow-up while that commit is still current. [CI scanning and merge verification](docs/SWARMSY_DOCTOR_NO_MIDDLEMAN.md#scan-prs-and-verify-the-merge)

For an open website support PR, Doctor can reapply the validated edits to a newer `main` and run isolated tests there. It keeps the same PR, invalidates any previous approval and starts fresh Codex review and CI for the new commit before asking for merge approval. A changed edit anchor, a failed isolated validation or an owner rejection needs review. Doctor requests the configured Full Linux workflow while Codex is reviewing and records dispatch permission errors. It reads the run's failed jobs and available GitHub annotations. A functional CI correction still requires local reproduction and must stay within the original repair scope.

Website support approval records the exact PR head. If the website base advanced after validation, return the case to review so Doctor can produce a current repair. [Case #2](https://github.com/Crypto-Moonboys/Crypto-Moonboys.github.io/pull/2270) verified the Telegram-approved GitHub merge. Merge status and live verification are separate checks.

Worker and D1 releases use the [website's protected Cloudflare workflow](https://github.com/Crypto-Moonboys/Crypto-Moonboys.github.io/blob/main/.github/workflows/cloudflare-pr-release.yml). Its release credentials live in the website repository's `cloudflare-production` environment. Doctor's WSL watcher needs its website GitHub credentials and local validation runtime. SAM editorial approvals run through the separate Brain bridge.

Website support repairs can require Brain's independent verdict after Codex and before the Telegram merge prompt. Enable `DADDY_DOCTOR_RELEASE_REVIEW_REQUIRED=true` on both the website worker and the Brain support bridge after installing the matching Brain code and deploying the Telegram Worker with D1 migration 139. Both services must share the website repair archive directory. Configure the website service's PATH and Codex CLI login for the read-only post-deployment review. Doctor matches the exact released files to live HTTP responses and asks Codex to review that evidence. **Auto** approves the displayed commit and authorizes one checked revert if Codex finds a live regression. A revert must restore the original files and pass the same tests, Codex and Brain review. If the live evidence is unavailable, the base advances or the revert fails checks, Doctor flags the case for attention.

## Repair intelligence

Doctor can search all local repairs, rank related successful and failed repairs, and optionally maintain a resumable GitHub issue/PR index and private R2 terminal lesson library. Run the sync commands separately from the repair watcher. Use `--intelligence-report` for aggregate repair outcomes and historical coverage. Configure `DADDY_DOCTOR_SHARED_REPOS` independently of GitHub history access. Shared lessons do not grant permission to repair or merge and are not a cross-host queue. See the [repair intelligence runbook](docs/DOCTOR_REPAIR_INTELLIGENCE.md) for setup, verification and remaining failover gates.

## Develop

```bash
python -m pytest -q
```

[Architecture](docs/ARCHITECTURE.md) · [Doctor runbook](docs/SWARMSY_DOCTOR_NO_MIDDLEMAN.md) · [SWARMSY integration direction](docs/SWARMSY_APP_DIRECTION.md) · [Historical repair and upgrade notes](docs/final-agent-direction.md)

### Distilled historical repair knowledge

The existing history sync now incrementally produces compact, source-linked local knowledge and filters routine review chatter. Use `--distillation-report` to inspect coverage and byte counts. Repair retrieval uses bounded cached advisory context rather than fetching historical discussions on demand. See the [repair intelligence runbook](docs/DOCTOR_REPAIR_INTELLIGENCE.md) for limitations and rollout.
