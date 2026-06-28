"""Shared primitives for LLT peer agents."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from llt_evaluator import RequirementEvaluator

from .message import AgentMessage
from .state import VerificationRunState


def normalize_term(term: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", term).strip("_")
    return cleaned.lower() or "term"


def render_json(data: Dict[str, object]) -> str:
    return json.dumps(data, indent=2, sort_keys=False, default=str)


@dataclass
class StageContext:
    runtime: "VerificationCoordinator"
    state: VerificationRunState
    evaluator: RequirementEvaluator
    poolside_client: object


class BaseStageAgent:
    """Small base class shared by the peer agents."""

    name = "BaseStageAgent"
    stage = "base"

    def __init__(self, context: StageContext):
        self.context = context

    @property
    def runtime(self) -> "VerificationCoordinator":
        return self.context.runtime

    @property
    def state(self) -> VerificationRunState:
        return self.context.state

    @property
    def evaluator(self) -> RequirementEvaluator:
        return self.context.evaluator

    @property
    def poolside(self):
        return self.context.poolside_client

    def emit(
        self,
        status: str,
        payload: Dict[str, object],
        evidence: Optional[Dict[str, object]] = None,
        notes: Optional[List[str]] = None,
        next_agent: Optional[str] = None,
    ) -> AgentMessage:
        message = AgentMessage(
            agent=self.name,
            stage=self.stage,
            status=status,
            payload=payload,
            evidence=evidence or {},
            notes=notes or [],
            next_agent=next_agent,
        )
        self.state.record(message)
        written = self.state.write_json(f"{len(self.state.messages):02d}_{self.stage}.json", message.to_dict())
        self.runtime.generated_files.append(str(written))
        return message
