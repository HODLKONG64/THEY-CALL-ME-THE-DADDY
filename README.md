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

## Develop

```bash
python -m pytest -q
```

[Architecture](docs/ARCHITECTURE.md) · [Doctor runbook](docs/SWARMSY_DOCTOR_NO_MIDDLEMAN.md) · [SWARMSY integration direction](docs/SWARMSY_APP_DIRECTION.md) · [Historical repair and upgrade notes](docs/final-agent-direction.md)
