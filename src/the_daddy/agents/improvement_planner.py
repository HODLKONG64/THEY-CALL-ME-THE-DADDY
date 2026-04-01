from __future__ import annotations

from ..models import ArchitectureReview, MemoryState


class ImprovementPlanner:
    def merge_review_into_backlog(self, memory: MemoryState, review: ArchitectureReview) -> list[str]:
        added = []
        for item in review.backlog_items:
            if item not in memory.backlog:
                memory.backlog.append(item)
                added.append(item)
        return added
