# THEY-CALL-ME-THE-DADDY (Daddy)

**Self-repairing maintenance agent for SWARMSY swarm coordination system.**

## Overview
This repo contains the core `the_daddy` Python package - an experimental, failure-driven, autonomous repo maintenance and self-evolution system.

It is designed to audit, diagnose, repair, and evolve the codebase safely with strict guardrails.

## Quick Links
- [Full Architecture](/docs/ARCHITECTURE.md)
- [SWARMSY App Direction](/docs/SWARMSY_APP_DIRECTION.md)
- [Doctor No-Middleman Flow](/docs/SWARMSY_DOCTOR_NO_MIDDLEMAN.md)
- [Failure Driven Repair Layer](README_FAILURE_DRIVEN_REPAIR_LAYER.md) (move to docs/ pending)

See `/docs/` for detailed design, safety rules, and operational memory.

## Setup
1. Copy `.env.example` to `.env` and fill in keys
2. `uv sync` or `pip install -e .`
3. Run `the-daddy` CLI or `python -m attempt_real_repair`

More details in the docs.