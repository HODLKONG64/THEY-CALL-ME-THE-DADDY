# SWARMSY Doctor Request Queue (v1)

SWARMSY can queue Doctor Requests when Daddy is busy/unavailable, then continue app flow while waiting for a Doctor response.

## v1 storage

- Create a GitHub issue in `HODLKONG64/THEY-CALL-ME-THE-DADDY`
- Apply labels: `doctor-request`, `target:swarmsy`
- Include request payload JSON in the issue body

## Request schema

```json
{
  "id": "doctor-request-YYYYMMDD-HHMMSS",
  "source_repo": "HODLKONG64/SWARMSY",
  "target_repo": "HODLKONG64/SWARMSY",
  "status": "queued",
  "priority": "normal",
  "problem_summary": "...",
  "requested_fix": "...",
  "failing_commands": [],
  "known_logs": [],
  "allowed_paths": [],
  "blocked_paths": [],
  "created_at": "...",
  "updated_at": "...",
  "response": {
    "doctor_run_id": null,
    "branch": null,
    "pr_url": null,
    "result": null
  }
}
```

## Status lifecycle

- `queued` → request created
- `waiting_for_doctor` → SWARMSY is waiting for Daddy pickup
- `pr_opened` → Daddy opened a SWARMSY PR and posted details
- `failed` → Daddy attempted fix but validation or delivery failed
- `blocked` → Daddy refused due to policy (allowlist/target-path/safety checks)
