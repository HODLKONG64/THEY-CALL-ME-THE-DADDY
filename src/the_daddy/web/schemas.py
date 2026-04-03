from __future__ import annotations

from pydantic import BaseModel

from ..models import ExternalProposal


class ProposalEnvelope(BaseModel):
    proposal: ExternalProposal
