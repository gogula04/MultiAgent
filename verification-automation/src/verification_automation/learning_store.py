"""Persistence helpers for the verification learning loop."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class LearningStore:
    """Store run history and reusable examples for future agent runs."""

    root_dir: Path

    @property
    def run_history_path(self) -> Path:
        return self.root_dir / "run_history.jsonl"

    @property
    def gold_examples_path(self) -> Path:
        return self.root_dir / "gold_examples.jsonl"

    @property
    def failure_examples_path(self) -> Path:
        return self.root_dir / "failure_examples.jsonl"

    @property
    def learning_summary_path(self) -> Path:
        return self.root_dir / "learning_summary.md"

    def ensure(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def record_run(self, record: dict[str, Any]) -> Path:
        self.ensure()
        payload = dict(record)
        payload.setdefault("timestamp", _now())
        return self._append_jsonl(self.run_history_path, payload)

    def record_gold_example(self, record: dict[str, Any]) -> Path:
        self.ensure()
        payload = dict(record)
        payload.setdefault("timestamp", _now())
        return self._append_jsonl(self.gold_examples_path, payload)

    def record_failure_example(self, record: dict[str, Any]) -> Path:
        self.ensure()
        payload = dict(record)
        payload.setdefault("timestamp", _now())
        return self._append_jsonl(self.failure_examples_path, payload)

    def write_learning_summary(self, text: str) -> Path:
        self.ensure()
        self.learning_summary_path.write_text(text)
        return self.learning_summary_path

    def load_recent_examples(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.gold_examples_path.exists():
            return []
        rows = [self._decode_line(line) for line in self.gold_examples_path.read_text().splitlines() if line.strip()]
        return rows[-limit:]

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> Path:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, default=_json_default, sort_keys=True))
            handle.write("\n")
        return path

    @staticmethod
    def _decode_line(line: str) -> dict[str, Any]:
        try:
            return json.loads(line)
        except Exception:
            return {"raw": line}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    return str(value)
