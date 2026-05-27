# THEY CALL ME THE DADDY

**Self-repairing autonomous development agent for SWARMSY swarm coordination.**

`the_daddy` is an experimental, failure-driven, multi-agent system designed to diagnose, repair, and evolve its own codebase (and eventually the full swarm). Built with strict safety guards, decision contracts, and phased stability checks.

## Philosophy & Core Features
- Failure-driven evolution instead of traditional dev cycles
- Multi-agent architecture (Planner, Reviewer, Diagnoser, Doctor takeover, Depth Learner)
- Bounded self-patching with risk classification and upgrade gates
- GitHub auto-PR + merge workflows
- R2 / Cloudflare memory layer
- CLI + FastAPI dashboard
- Phase-based stability (see `phase2_stability_checklist.json` & `decision_contract.json`)

## Safety & Target Repo Configuration
Daddy has strong built-in safety guards:
- `DADDY_ALLOWED_TARGET_REPOS` controls which repositories Daddy can push/PR/merge to (defaults to self-repair on this repo only)
- `DADDY_SWARMSY_AUTO_MERGE` controls auto-merge behavior in SWARMSY external mode (defaults to `false` — opens PRs only)
- See [`docs/SWARMSY_DOCTOR_NO_MIDDLEMAN.md`](docs/SWARMSY_DOCTOR_NO_MIDDLEMAN.md) for the full no-middleman queue flow and doctor mode details.

## Quick Start
1. Clone & install
   ```bash
   git clone https://github.com/HODLKONG64/THEY-CALL-ME-THE-DADDY.git
   cd THEY-CALL-ME-THE-DADDY
   # Recommended: uv sync or pip install -e .
   ```
2. Setup environment
   ```bash
   cp .env.example .env
   # Fill your OpenAI key, GitHub token, R2 credentials, etc.
   ```
3. Run self-repair
   ```bash
   python attempt_real_repair.py
   ```
4. Start CLI / dashboard (see `src/the_daddy/cli.py`)

## Architecture
See [`docs/architecture.md`](docs/architecture.md) for full lanes, commit gating, engine details, and agent flow.

## Failure-Driven Repair Layers
See [`docs/failure-driven-repair-layer.md`](docs/failure-driven-repair-layer.md) — the core self-healing mechanism.

## OpenAI Upgrade Gate & Safety
See [`docs/openai-upgrade-gate.md`](docs/openai-upgrade-gate.md) — how the system protects itself during model/LLM changes.

## Additional Documentation
- [`docs/final-agent-direction.md`](docs/final-agent-direction.md)
- [`docs/level2-safe.md`](docs/level2-safe.md) (legacy safety notes)
- [`docs/original-build-fix.md`](docs/original-build-fix.md) (historical context)
- `system_rules.json`, `decision_contract.json`, `phase2_stability_checklist.json`

## Current Status
Unfinished hookups (LLM client, R2 memory, full SWARMSY integration) are being prioritized next. Some "wants" are still placeholders/fake — we will replace them systematically.

## Development / Self-Repair
The system is designed to help *you* improve it. Run `attempt_real_repair.py` or let Daddy take over.

---

**Built with ❤️ for SWARMSY** — they call me the Daddy.