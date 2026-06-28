"""Typed messages exchanged between LLT verification peer agents."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentMessage:
    """A validated handoff between peer agents."""

    agent: str
    stage: str
    status: str
    payload: Dict[str, Any] = field(default_factory=dict)
    evidence: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    next_agent: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
