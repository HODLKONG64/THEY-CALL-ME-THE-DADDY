# Doctor queue and repair archive

One Doctor worker can process a persistent queue for its configured GitHub repository. The CLI can enqueue requests directly. A SWARMSY frontend can submit the same request shape through a server-side adapter, then show the archive ID, status and PR link. That frontend adapter is a separate integration.

## How a repair runs

1. Doctor reads the queued problem, scope, supplied logs, and repository files. It tries the exact edits from a matching merged repair when they still apply.
2. Doctor asks the OpenAI API for concrete edits, checks the allowed paths and exact text anchors, and applies the edits in a disposable checkout. It runs the operator's tests in a container with no network or credentials. A failed test becomes evidence for the next repair attempt.
3. Doctor sends the candidate and test result back to the API. It requires either replacement edits or a positive verdict tied to the tested diff. It records the verdict and sanitized evidence in the repair archive. Missing evidence or exhausted attempts produce an explicit failure.
4. After a passing test and positive API review, Doctor pushes a repair branch and opens a PR. It requests `@codex review` for the exact commit and asks for a concrete fix with each finding.
5. On later polls Doctor reads the Codex result. It sends actionable findings or failed required checks, previous logs, and the current files back to the API. Each follow-up commit goes through validation, API approval and a fresh Codex review. The review cycle count survives restarts.
6. Doctor can merge after Codex approves the validated head and configured CI checks pass. GitHub must report the PR is mergeable. Doctor sends the reviewed SHA with the merge request and records success only when GitHub confirms the merge.

Doctor accepts a completed review from the Codex GitHub bot on the expected commit, with an explicit approval or its commit-specific approval marker. It also recognizes the bot's completed review summary when it reports a clean result for that commit. Where the bot leaves a positive reaction on Doctor's commit-specific request, that reaction can identify the reviewed commit too. Silence, progress reactions and PR-wide reactions leave the request pending. A moved base, an externally changed head, or a human changes-requested review stops automatic delivery and records the reason.

## Configure a worker

Use a Linux host with Python 3.11+, Git and Docker. Keep the archive on a persistent local filesystem with access limited to the worker and authorized operators. Queue writers on the same host should use the CLI or `JsonDoctorArchive.upsert_request` so they share its write lock.

| Setting | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Access to the configured repair and review models. |
| `GITHUB_TOKEN` | GitHub user token with target repo contents and pull request write access, and checks and commit statuses read access. Use a Codex-connected account subject to branch protections. Require up-to-date checks on the production branch before enabling automatic merge. |
| `GITHUB_REPO` | One target per worker. Configure the Codex GitHub integration on this repository. |
| `DADDY_ALLOWED_TARGET_REPOS` | Comma-separated repo allowlist. Defaults to Daddy only. |
| `DADDY_DOCTOR_ARCHIVE_FILE` | Shared local JSON archive path. Defaults to `doctor_local/swarmsy_repair_archive.json`. |
| `DADDY_DOCTOR_VALIDATION_IMAGE` | Trusted Docker image already on the worker host with the target's test dependencies installed. |
| `DADDY_DOCTOR_TEST_COMMAND` | Operator-selected executable and arguments, for example `python -m pytest -q`. The worker does not run commands supplied by the API or queue entries. |
| `DADDY_DOCTOR_REQUIRED_CHECKS` | Comma-separated CI check names. If empty, Doctor can open and review PRs and leaves the merge to you. Daddy's CI job is named `tests`. |
| `DADDY_SWARMSY_AUTO_MERGE` | Set to `true` to enable guarded automatic merging for SWARMSY. Defaults to `false`. |
| `DADDY_MAX_ATTEMPTS` | API correction budget for each repair or follow-up. Defaults to 4 and caps at 8. |
| `DADDY_SWARMSY_REVIEW_MAX_CYCLES` | Follow-up commit budget per PR. Defaults to 3 and caps at 8. |

For Daddy, build a validation image with Python, the repository's installed dependencies, and pytest. The worker mounts a fresh copy of the candidate source under `/workspace` at test time. For SWARMSY, use a Node image with its test dependencies and set a command that runs offline. The image and dependency setup stay under operator control.

Build Daddy's validation image from the repository root and set `DADDY_DOCTOR_VALIDATION_IMAGE=daddy-validation` in `.env`.

```bash
docker build -t daddy-validation -f - . <<'DOCKERFILE'
FROM python:3.11-slim
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml .
RUN python -m pip install --no-cache-dir .
DOCKERFILE
```

```bash
python -m the_daddy.swarmsy_doctor_queue --enqueue 'Fix the upload regression' --allow-path src/ --allow-path tests/ --log-file ./test-output.log
python -m the_daddy.swarmsy_doctor_queue --watch --interval 60
python -m the_daddy.swarmsy_doctor_queue --show-recent
```

Run `--watch` under a service supervisor for restart recovery. The GitHub Actions **Doctor CI** workflow runs the repository tests. Put the queue worker on a host with the persistent archive and configured validation image.

## Archive states

| State | Meaning |
| --- | --- |
| `queued` / `running` | Accepted or being repaired. Delivery checkpoints let the worker reconcile a crash around push or PR creation. |
| `pr_opened_waiting_review` | The PR remains tracked for Codex, CI, or a manual merge. Exhausted review cycles stop further patching. |
| `merged` | GitHub confirmed the expected PR head was merged. Scoped edits from this repair can be retried for a matching future failure. |
| `blocked_needs_human_permission` | The request needs human intervention, for example because its scope or PR state changed. |
| `failed_with_reason` | Repair ended without a validated fix. The archive contains the recorded evidence. |

The archive includes a status timeline, API verdicts, validation output, PR and commit identifiers, and replayable edits. Existing archive records without an attested PR head require manual review. The focused worker uses this archive for repair memory, while the legacy wake engine keeps its separate R2/local memory.

## Scan PRs and verify the merge

Set `DADDY_DOCTOR_WATCH_CI=true` for the existing queue worker and give its
GitHub token Actions read access. The website uses **Full Linux Test Suite**
and Daddy uses **Doctor CI**. Configure the target's required GitHub checks as
before. Keep the website worker's existing Telegram approval path for cases
opened by Brain.

```sh
python -m the_daddy.swarmsy_doctor_queue --scan-prs
```

This reports the latest 25 open PRs into the target's default branch, with
exact-head CI, draft and pause states. The watcher checks periodically and
picks up a same-repository PR when it has the `doctor:repair-ci` label, a
failed functional test step, and one to five eligible changed source files.
The isolated validation command must reproduce a failure before Doctor proposes a
patch. Changes are confined to the selected files. Drafts and PRs labelled
`doctor:paused` stay untouched while paused. Forks, protected paths,
test-only changes, conflicts, and CI infrastructure failures stay with
the operator. Create the labels in the target repository before using them.

An adopted or post-merge follow-up PR needs the separate
`doctor:merge-ci` label for Doctor to merge it. The exact new head must pass
Codex review, the named CI suite, and configured required checks. GitHub
still enforces its own branch rules. Reviewed website support PRs retain
the existing commit-specific Telegram merge approval.

After a tracked PR merges, `--show-recent` includes the CI status and link for
the **merge commit**, separately from deployment. Turning off CI watching
pauses pending CI records without blocking repairs or deployment tracking.
Use the test workflow on
that commit, or set `DADDY_DOCTOR_DISPATCH_CI=true` to let Doctor request a
missing run on the current ref with Actions write permission. Doctor
checks the returned run's SHA before using it. Start the first failing
check on an untracked PR through GitHub so the scanner has evidence to adopt it.

If the exact merge commit still heads the default branch and its functional
test fails in repairable scope, Doctor queues one follow-up PR with the same
file scope and validates it before publishing. An advanced branch, an
unreproduced failure, or a failed follow-up needs review. This CI lane
does not run Cloudflare deployments or migrations.

## Cloudflare Worker deployment

For a target with a Cloudflare Worker and an existing deploy workflow triggered by a push to the production branch, set `DADDY_DOCTOR_CLOUDFLARE_WORKFLOW` to the workflow filename, such as `deploy-worker.yml`, and `DADDY_DOCTOR_CLOUDFLARE_JOB` to its actual deploy job name in GitHub. The Doctor token also needs Actions read access. The target workflow owns the Cloudflare credentials and production environment. Doctor records the merged commit, watches its push-triggered workflow run and shows the deployment result and link in `--show-recent`.

Targets that already have a Wrangler Worker config can use the [reusable deployment workflow](../.github/workflows/cloudflare-workers-deploy.yml). Pin the reference to a reviewed commit of this repository. Configure the production environment and Cloudflare secrets in the target repository.

```yaml
name: Deploy Worker

on:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  deploy:
    uses: HODLKONG64/THEY-CALL-ME-THE-DADDY/.github/workflows/cloudflare-workers-deploy.yml@REVIEWED_DADDY_COMMIT_SHA
    with:
      production_branch: main
      working_directory: .
    secrets:
      cloudflare_api_token: ${{ secrets.CLOUDFLARE_API_TOKEN }}
      cloudflare_account_id: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
```

The deployment job checks out the exact push commit. Doctor keeps source review and merge gates upstream of deployment. If a target already uses Cloudflare's Git integration, its connected production branch deploys after a merge. The workflow tracker above applies to targets deployed through GitHub Actions. Native, desktop, and on-device installation steps still use their platform pipelines.
