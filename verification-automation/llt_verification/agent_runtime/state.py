"""Run state for the LLT verification agent pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .message import AgentMessage


@dataclass
class VerificationRunState:
    """Holds the evolving state of a single verification run."""

    workspace_root: Path
    requirement_prompt: str
    requirement_id: str
    run_dir: Path
    messages: List[AgentMessage] = field(default_factory=list)
    packages: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    artifacts: Dict[str, str] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)
    stage_order: List[str] = field(default_factory=list)
    policy: Dict[str, Any] = field(default_factory=dict)
    audit_events: List[Dict[str, Any]] = field(default_factory=list)
    run_manifest: Dict[str, Any] = field(default_factory=dict)

    def log(self, message: str, level: str = "INFO") -> str:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] [{level}] {message}"
        self.logs.append(entry)
        return entry

    def record(self, message: AgentMessage) -> None:
        self.messages.append(message)
        self.stage_order.append(message.stage)
        self.packages[message.stage] = message.to_dict()
        self.audit_events.append(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "event": "agent_message",
                "agent": message.agent,
                "stage": message.stage,
                "status": message.status,
                "next_agent": message.next_agent,
            }
        )

    def write_json(self, name: str, payload: Dict[str, Any]) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        path = self.run_dir / name
        path.write_text(json.dumps(payload, indent=2, sort_keys=False, default=str))
        self.audit_events.append(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "event": "write_json",
                "path": str(path),
            }
        )
        return path

    def write_text(self, name: str, text: str) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        path = self.run_dir / name
        path.write_text(text)
        self.audit_events.append(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "event": "write_text",
                "path": str(path),
            }
        )
        return path
