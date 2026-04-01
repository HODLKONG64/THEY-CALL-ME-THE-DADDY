from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from ..models import AgentReputation, ArchitectureReview, MemoryState, RunRecord, VetDecision
from .r2_store import R2Store


def now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class MemoryRepository:
    def __init__(self, store: R2Store) -> None:
        self.store = store
        raw = self.store.load_json("the-daddy/memory.json")
        self.state = MemoryState.model_validate(raw or {})

    def save(self) -> None:
        self.state.updated_at = datetime.now(timezone.utc).isoformat()
        self.store.save_json("the-daddy/memory.json", self.state.model_dump(mode="json"))

    def add_architecture_review(self, review: ArchitectureReview) -> None:
        self.state.architecture_reviews.append(review)
        self.state.backlog.extend([item for item in review.backlog_items if item not in self.state.backlog])
        self.save()

    def add_run(self, run: RunRecord) -> None:
        self.state.run_index.append(run.run_id)
        self.store.save_json(f"the-daddy/runs/{run.run_id}.json", run.model_dump(mode="json"))
        self.save()

    def add_quarantine_event(self, event: dict) -> None:
        self.state.quarantine_events.append(event)
        self.store.save_json(f"the-daddy/quarantine/{now_slug()}-{event['agent_id']}.json", event)
        self.save()

    def update_reputation(self, agent_id: str, decision: VetDecision) -> AgentReputation:
        rep = self.state.reputations.get(agent_id) or AgentReputation(agent_id=agent_id)
        rep.apply(decision.route, decision.reputation_delta)
        self.state.reputations[agent_id] = rep
        self.save()
        return rep

    def record_failure_pattern(self, signature: str, payload: dict, success: bool) -> None:
        bucket = self.state.successful_fixes if success else self.state.failed_fixes
        bucket.setdefault(signature, []).append(payload)
        self.state.failure_patterns.setdefault(signature, {"seen": 0})
        self.state.failure_patterns[signature]["seen"] += 1
        self.save()

    def record_improvement_result(self, title: str, *, applied: bool, payload: dict) -> None:
        bucket = self.state.accepted_improvements if applied else self.state.rejected_improvements
        if title not in bucket:
            bucket.append(title)
        self.state.improvement_history.append(
            {
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "title": title,
                "applied": applied,
                "payload": payload,
            }
        )
        self.save()

    def latest_review(self):
        return self.state.architecture_reviews[-1] if self.state.architecture_reviews else None

    @staticmethod
    def fingerprint(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
