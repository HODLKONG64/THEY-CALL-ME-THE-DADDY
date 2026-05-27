# OpenAI Upgrade Gate Pack

This pack adds a hard workflow gate.

The workflow must not move forward until OpenAI gives upgrade advice.

## What it does

1. Builds a repo snapshot
2. Sends that snapshot to OpenAI
3. Receives structured upgrade advice
4. Validates the advice
5. Stops the workflow if OpenAI does not approve proceeding

## Why it exists

Your current agent can stay alive by producing safe filler patches.

This gate forces an explicit OpenAI audit before the main agent run continues.

## Files

- `.github/workflows/main_with_openai_upgrade_gate.yml`
- `src/the_daddy/core/request_upgrade_advice.py`
- `src/the_daddy/core/require_upgrade_advice.py`
- `src/the_daddy/core/upgrade_advice_schema.json`
- `src/the_daddy/core/upgrade_gate_rules.json`

## Expected secrets

- `OPENAI_API_KEY`
- `GITHUB_TOKEN`
- `R2_ENDPOINT_URL`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`

## Important

This enforces the workflow gate.

For full runtime enforcement inside the agent itself, the next integration step is to make `engine.py` refuse to patch when `DADDY_UPGRADE_ADVICE_PATH` is missing or not approved.
