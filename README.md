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
- Doctor can merge its PR after a completed Codex review of the current commit, all configured CI checks pass, and GitHub permits the merge. Changes to protected files require a manual merge.
- `DADDY_SWARMSY_AUTO_MERGE` defaults to `false`. SWARMSY requests still get tested, published and reviewed in this mode.
- For configured Cloudflare Workers, the [deployment workflow and tracking setup](docs/SWARMSY_DOCTOR_NO_MIDDLEMAN.md#cloudflare-worker-deployment) can ship and verify a reviewed merge.
- The legacy `the_daddy.cli` engine remains available for diagnostics and manual PR review. The queue worker handles automatic review follow-up and merge.

## Website support and CI tracking

The Brain sends approved website repair cases to the website-scoped Doctor service. Doctor reproduces the failure, tests the repair in isolation and requests Codex review. The owner can approve the exact reviewed commit in `@WIKICOMSBOT`. [Website support setup](https://github.com/HODLKONG64/the-brain/blob/main/support-ops/README.md)

Use `--scan-prs` for a read-only CI inventory. `DADDY_DOCTOR_WATCH_CI=true` enables ongoing tracking. `DADDY_DOCTOR_DISPATCH_CI=true` lets Doctor request missing checks for tracked commits with a website-scoped token that has Actions write access. Doctor can adopt an eligible functional failure tagged `doctor:repair-ci` after reproducing it. `doctor:merge-ci` enables the separate CI merge path after Codex and required GitHub checks pass. Doctor records post-merge checks against the merge SHA and can queue one scoped follow-up while that commit is still current. [CI scanning and merge verification](docs/SWARMSY_DOCTOR_NO_MIDDLEMAN.md#scan-prs-and-verify-the-merge)

Website support approval records the exact PR head. If the website base advanced after validation, return the case to review so Doctor can produce a current repair. [Case #2](https://github.com/Crypto-Moonboys/Crypto-Moonboys.github.io/pull/2270) verified the Telegram-approved GitHub merge. Merge status and live verification are separate checks.

Worker and D1 releases use the [website's protected Cloudflare workflow](https://github.com/Crypto-Moonboys/Crypto-Moonboys.github.io/blob/main/.github/workflows/cloudflare-pr-release.yml). Its release credentials live in the website repository's `cloudflare-production` environment. Doctor's WSL watcher needs its website GitHub credentials and local validation runtime. SAM editorial approvals run through the separate Brain bridge.

## Repair intelligence

Doctor can search all local repairs, rank related successful and failed repairs, and optionally maintain a resumable GitHub issue/PR index and private R2 terminal lesson library. Run the sync commands separately from the repair watcher. Use `--intelligence-report` for aggregate repair outcomes and historical coverage. Configure `DADDY_DOCTOR_SHARED_REPOS` independently of GitHub history access. Shared lessons do not grant permission to repair or merge and are not a cross-host queue. See the [repair intelligence runbook](docs/DOCTOR_REPAIR_INTELLIGENCE.md) for setup, verification and remaining failover gates.

## Develop

```bash
python -m pytest -q
```

[Architecture](docs/ARCHITECTURE.md) · [Doctor runbook](docs/SWARMSY_DOCTOR_NO_MIDDLEMAN.md) · [SWARMSY integration direction](docs/SWARMSY_APP_DIRECTION.md) · [Historical repair and upgrade notes](docs/final-agent-direction.md)
