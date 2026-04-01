# THEY-CALL-ME-THE-DADDY

A full OpenAI-powered debugging and self-improvement swarm for software repos.

## What it does.

- Runs your repo command (tests, app start, lint, etc.)
- Watches logs and stack traces
- Asks OpenAI for:
  - architecture review at wake-up
  - runtime diagnosis
  - safe patch plan
  - external-agent vetting
  - self-improvement recommendations
- Applies bounded file patches
- Reruns verification
- Saves every run, recommendation, reputation score, and decision to Cloudflare R2
- Hosts a small dashboard API for inspecting health, memory, and recent runs
- Maintains an external-agent quarantine pipeline:
  - unknown agent proposal
  - OpenAI vetting
  - hard policy checks
  - reputation update
  - staging/trust decision

## Core design

### Wake cycle
1. Load durable memory from Cloudflare R2
2. Read latest repo state and recent run history
3. Run OpenAI architecture audit
4. Save advisory + backlog
5. Execute debugging workflow
6. Verify results
7. Save everything back to R2

### Agent graph
- **Wake Auditor**: audits structure, drift, and missing safeguards
- **Diagnoser**: turns logs and stack traces into root-cause hypotheses
- **Patch Planner**: suggests minimal targeted changes
- **Vetter**: reviews unknown-agent submissions
- **Verifier**: reruns command and decides pass/fail
- **Improvement Planner**: converts advice into backlog entries
- **Risk Gate**: classifies changes into safe / branch / recommend-only

### Memory
Durable state is stored in Cloudflare R2 under a single object:
- `the-daddy/memory.json`

Per-run artifacts are also stored:
- `the-daddy/runs/<timestamp>.json`
- `the-daddy/quarantine/<timestamp>-<agent>.json`
- `the-daddy/advisories/<timestamp>.json`

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Set your environment variables in `.env`, then run:

```bash
daddy run
```

Start the dashboard API:

```bash
daddy-api
```

## External agent intake

Submit an unknown-agent proposal:

```bash
daddy submit-proposal --agent-id scout-1 --file proposal.json
```

The system will:
- quarantine it
- send it to OpenAI vetting
- run hard policy rules
- update reputation
- accept, stage, or reject

## GitHub Actions

Workflow file:
- `.github/workflows/daddy-cycle.yml`

It runs every 12 hours and on manual dispatch.

## Notes

This is a bounded self-healing system for debugging and maintenance.

It is **not** a free-for-all autonomous shell bot.
High-risk actions are blocked unless you explicitly wire those permissions in yourself.
