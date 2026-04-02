from __future__ import annotations

from dataclasses import dataclass, asdict
from time import time
from typing import Dict, List


@dataclass
class TraceEvent:
    name: str
    ts: float
    data: Dict


class TraceBuffer:
    def __init__(self) -> None:
        self.events: List[TraceEvent] = []

    def add(self, name: str, **data) -> None:
        self.events.append(TraceEvent(name=name, ts=time(), data=data))

    def export(self) -> List[Dict]:
        return [asdict(e) for e in self.events]
