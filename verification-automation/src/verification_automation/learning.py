"""Dedicated learning agent for feedback-driven verification improvement."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .learning_store import LearningStore
from .state import VerificationState


@dataclass(slots=True)
class LearningAgent:
    """Persist run outcomes so later agent runs can reuse the evidence."""

    def process(self, state: VerificationState, output_dir: Path) -> VerificationState:
        store = LearningStore(output_dir / "learning")
        record = self._build_record(state)
        run_path = store.record_run(record)

        if record["outcome"] == "verified":
            example_path = store.record_gold_example(record)
            artifact_paths = {
                "learning/run_history.jsonl": str(run_path),
                "learning/gold_examples.jsonl": str(example_path),
                "learning/learning_summary.md": str(store.write_learning_summary(self._render_summary(record, run_path, example_path, None))),
            }
        elif record["outcome"] in {"blocked", "needs_attention"}:
            failure_path = store.record_failure_example(record)
            artifact_paths = {
                "learning/run_history.jsonl": str(run_path),
                "learning/failure_examples.jsonl": str(failure_path),
                "learning/learning_summary.md": str(store.write_learning_summary(self._render_summary(record, run_path, None, failure_path))),
            }
        else:
            artifact_paths = {
                "learning/run_history.jsonl": str(run_path),
                "learning/learning_summary.md": str(store.write_learning_summary(self._render_summary(record, run_path, None, None))),
            }

        state["learning_status"] = "recorded"
        state["learning_record"] = record
        state["learning_summary_text"] = self._render_summary(record, run_path, artifact_paths.get("learning/gold_examples.jsonl"), artifact_paths.get("learning/failure_examples.jsonl"))
        state["learning_store_path"] = str(store.root_dir)
        state["learning_artifacts"] = artifact_paths
        state.setdefault("artifacts", {}).update(artifact_paths)
        if isinstance(state.get("proof_report"), dict):
            state["proof_report"]["artifacts"] = dict(state.get("artifacts", {}))
        state.setdefault("logs", []).append(
            f"Learning agent recorded {record['outcome']} run memory at {store.root_dir}."
        )
        return state

    def _build_record(self, state: VerificationState) -> dict[str, Any]:
        test_results = state.get("test_results", {})
        coverage = state.get("coverage", [])
        proof_report = state.get("proof_report", {})
        outcome = self._infer_outcome(state)
        return {
            "requirement_identifier": state.get("requirement_identifier", ""),
            "requirement_name": state.get("requirement_name", ""),
            "requirement_resolution_status": state.get("requirement_resolution_status", ""),
            "mode": state.get("mode", "Direct"),
            "status": state.get("status", ""),
            "review_status": state.get("review_status", ""),
            "outcome": outcome,
            "bold_terms": list(state.get("requirement_bold_terms", [])),
            "mappings_count": len(state.get("mappings", [])),
            "dd_count": len(state.get("dd_rows", [])),
            "coverage_count": len(coverage),
            "passed_tests": bool(test_results.get("passed", False)),
            "executed_tests": int(test_results.get("executed", 0)),
            "failed_tests": int(test_results.get("failed", 0)),
            "failure_classification": list(state.get("failure_classification", [])),
            "unresolved": list(state.get("unresolved", [])),
            "manual_review": list(state.get("manual_review", [])),
            "review_notes": state.get("review_notes", ""),
            "proof_conclusion": proof_report.get("conclusion", ""),
            "artifacts": dict(state.get("artifacts", {})),
        }

    def _infer_outcome(self, state: VerificationState) -> str:
        if state.get("status") == "blocked":
            return "blocked"
        if state.get("status") == "repair_needed":
            return "needs_attention"
        test_results = state.get("test_results", {})
        coverage = state.get("coverage", [])
        proof = state.get("proof_report", {})
        if test_results.get("passed", False) and proof and coverage:
            if state.get("review_status") == "approved":
                return "verified"
            return "draft_verified"
        return "needs_attention"

    def _render_summary(
        self,
        record: dict[str, Any],
        run_path: Path,
        gold_path: str | Path | None,
        failure_path: str | Path | None,
    ) -> str:
        lines = [
            "# Learning Agent Summary",
            "",
            f"- Requirement: {record.get('requirement_identifier', '')}",
            f"- Name: {record.get('requirement_name', '')}",
            f"- Mode: {record.get('mode', '')}",
            f"- Outcome: {record.get('outcome', '')}",
            f"- Review Status: {record.get('review_status', '') or 'unknown'}",
            f"- Run History: {run_path}",
        ]
        if gold_path:
            lines.append(f"- Gold Example: {gold_path}")
        if failure_path:
            lines.append(f"- Failure Example: {failure_path}")
        lines.extend(
            [
                "",
                "## What Was Learned",
                f"- Requirement resolution: {record.get('requirement_resolution_status', '') or 'unknown'}",
                f"- Bolded terms captured: {len(record.get('bold_terms', []))}",
                f"- DD rows generated: {record.get('dd_count', 0)}",
                f"- Coverage items: {record.get('coverage_count', 0)}",
                f"- Tests executed: {record.get('executed_tests', 0)}",
                f"- Tests passed: {record.get('passed_tests', False)}",
                "",
                "## Feedback Use",
                "- Verified runs are stored as reusable examples.",
                "- Blocked or failed runs are stored as failure examples.",
                "- Future runs can reuse these records as retrieval evidence.",
            ]
        )
        return "\n".join(lines) + "\n"


def learn_from_run(state: VerificationState, output_dir: Path) -> VerificationState:
    """Record the run outcome as durable learning memory."""

    agent = LearningAgent()
    return agent.process(state, output_dir)
