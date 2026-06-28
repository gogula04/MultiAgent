"""Shared primitives for LLT multi-agent stages."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from llt_evaluator import RequirementEvaluator

from .message import AgentMessage
from .policy import VerificationPolicy
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
    policy: VerificationPolicy


class BaseStageAgent:
    """Small base class shared by the multi-agent stages."""

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

    @property
    def policy(self) -> VerificationPolicy:
        return self.context.policy

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
        self.state.log(
            f"{self.name} [{self.stage}] -> {status}"
            + (f", next={next_agent}" if next_agent else "")
        )
        written = self.state.write_json(f"{len(self.state.messages):02d}_{self.stage}.json", message.to_dict())
        self.runtime.generated_files.append(str(written))
        return message
