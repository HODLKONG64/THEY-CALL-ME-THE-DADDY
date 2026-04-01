# Architecture

## Runtime lanes

- Wake review lane
- Debugging lane
- External proposal lane
- Memory persistence lane
- Dashboard lane

## Risk routes

- safe: auto-apply bounded source patches
- branch: stage/review changes such as workflows
- recommend: no auto-apply, backlog only
- reject: blocked

## Durable memory model

- architecture_reviews
- run_index
- backlog
- accepted_improvements
- rejected_improvements
- failure_patterns
- successful_fixes
- failed_fixes
- reputations
- quarantine_events
