from __future__ import annotations

from ..models import AgentReputation


def explain_reputation(rep: AgentReputation) -> str:
    return (
        f"agent={rep.agent_id} trust={rep.trust_score} "
        f"accepted={rep.accepted_count} staged={rep.staged_count} rejected={rep.rejected_count}"
    )
