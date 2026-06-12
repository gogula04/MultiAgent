"""Top-level orchestration for the verification automation workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agents import (
    analyze_coverage,
    build_dd,
    build_proof,
    build_setup_and_tests,
    discover_repository,
    intake_requirement,
    learn,
    load_model,
    map_source_and_dictionaries,
    parse_requirement,
    resolve_requirement_state,
    review_drafts,
    select_strategy,
    write_outputs,
)
from .config import AppConfig
from .execution import execute_generated_tests
from .rapita import run_rapita_pipeline
from .triage import triage_failures
from .state import VerificationState


@dataclass
class VerificationOrchestrator:
    """Run the verification workflow end-to-end."""

    config: AppConfig

    @classmethod
    def create(cls, repo_root: Path | None = None) -> "VerificationOrchestrator":
        return cls(config=AppConfig.load(repo_root=repo_root))

    def run(
        self,
        requirement_identifier: str,
        requirement_text: str = "",
        source_snippet: str = "",
        output_dir: Path | None = None,
        mode_override: str = "",
    ) -> VerificationState:
        artifact_dir = output_dir if output_dir is not None else (self.config.repo_root / "artifacts")
        state: VerificationState = {
            "requirement_identifier": requirement_identifier,
            "requirement_name": "",
            "requirement_text": requirement_text,
            "source_snippet": source_snippet,
            "mode_override": mode_override,
            "output_dir": str(artifact_dir),
            "related_requirements": [],
            "logs": [],
            "assumptions": [],
            "unresolved": [],
            "manual_review": [],
            "repair_attempts": 0,
            "rapita_plan": [],
            "rapita_results": {},
            "rapita_config_text": "",
            "rapita_node_mapping_text": "",
            "review_status": "",
            "review_notes": "",
            "review_decision": {},
            "traceability_notes_text": "",
            "failure_classification": [],
            "suggested_fix_report": "",
            "artifacts": {},
        }

        validation_error = self._validate_startup_gate(state)
        if validation_error is not None:
            return learn(validation_error, artifact_dir)

        model = load_model(self.config)
        state = intake_requirement(state)
        state = resolve_requirement_state(state, self.config)
        if state.get("status") == "blocked":
            state = self._blocked_state(
                state,
                state.get("requirement_resolution_notes", "Requirement could not be resolved."),
                artifact_dir,
            )
            return learn(state, artifact_dir)
        state = discover_repository(state, self.config)
        state = parse_requirement(state, model)
        state = map_source_and_dictionaries(state, model)
        state = select_strategy(state, model)
        state = build_dd(state, model)
        state = build_setup_and_tests(state, self.config)
        state = write_outputs(state, artifact_dir)
        state = review_drafts(state, model, self.config)
        state = write_outputs(state, artifact_dir)
        if state.get("review_status") != "approved":
            state["status"] = "awaiting_review"
            return state
        state = execute_generated_tests(state, artifact_dir)
        if not state.get("test_results", {}).get("passed", False):
            state = triage_failures(state, artifact_dir)
            state = build_setup_and_tests(state, self.config)
            state = write_outputs(state, artifact_dir)
            state = review_drafts(state, model, self.config)
            state = write_outputs(state, artifact_dir)
            if state.get("review_status") != "approved":
                state["status"] = "awaiting_review"
                return state
            state = execute_generated_tests(state, artifact_dir)
            if not state.get("test_results", {}).get("passed", False):
                state = triage_failures(state, artifact_dir)
        state = run_rapita_pipeline(state, self.config, artifact_dir)
        state = analyze_coverage(state, model)
        state = build_proof(state, model)
        state = learn(state, artifact_dir)
        state = write_outputs(state, artifact_dir)

        return state

    def run_to_directory(
        self,
        requirement_identifier: str,
        requirement_text: str = "",
        source_snippet: str = "",
        output_dir: Path | None = None,
        mode_override: str = "",
    ) -> VerificationState:
        return self.run(
            requirement_identifier=requirement_identifier,
            requirement_text=requirement_text,
            source_snippet=source_snippet,
            output_dir=output_dir,
            mode_override=mode_override,
        )

    def _validate_startup_gate(self, state: VerificationState) -> VerificationState | None:
        repo_root = self.config.repo_root.expanduser()
        identifier = (state.get("requirement_identifier") or "").strip()
        requirement_text = (state.get("requirement_text") or "").strip()
        source_snippet = (state.get("source_snippet") or "").strip()

        if not repo_root.exists():
            return self._blocked_state(state, f"Repo root does not exist: {repo_root}")

        if not identifier:
            return self._blocked_state(state, "Requirement ID or name is required.")

        if not self._repo_has_expected_layout(repo_root):
            return self._blocked_state(
                state,
                f"Repo root '{repo_root}' does not contain the expected verification layout. "
                "Select the company repo root with requirements/, software/source/, and verification/.",
            )

        return None

    def _repo_has_expected_layout(self, repo_root: Path) -> bool:
        expected_paths = [
            repo_root / "requirements" / "HLR",
            repo_root / "requirements" / "LLR",
            repo_root / "requirements" / "data_dictionary",
            repo_root / "software" / "source",
            repo_root / "verification" / "test-cases",
            repo_root / "verification" / "test-procedures",
        ]
        return all(path.exists() for path in expected_paths)

    def _blocked_state(self, state: VerificationState, reason: str, output_dir: Path | None = None) -> VerificationState:
        state["status"] = "blocked"
        state["mode"] = "not selected"
        state["review_status"] = "not reviewed"
        state["review_notes"] = reason
        state["review_decision"] = {
            "is_safe": False,
            "risk_score": 10,
            "summary": reason,
            "suggested_fix": "Paste the full requirement text or select the correct company repo root.",
            "tags": ["blocked", "validation", "repository"],
        }
        state["proof_report"] = {
            "summary": "No proof generated.",
            "conclusion": reason,
            "coverage": [],
            "test_results": {},
        }
        state["artifacts"] = {}
        state["dd_rows"] = []
        state["mappings"] = []
        state["behaviors"] = []
        state["data_dictionary_text"] = ""
        state["uut_dictionary_text"] = ""
        state["rvstest_text"] = ""
        state["python_test_text"] = ""
        state["rapita_config_text"] = ""
        state["rapita_node_mapping_text"] = ""
        state["traceability_notes_text"] = ""
        state["rapita_plan"] = []
        state["rapita_results"] = {
            "enabled": False,
            "executed": False,
            "success": False,
            "commands": [],
            "logs": [f"Blocked before execution: {reason}"],
            "summary": "Pipeline blocked before artifact generation.",
            "support_files": {},
        }
        state.setdefault("logs", []).append(f"Blocked: {reason}")
        state["unresolved"] = [reason]
        state["manual_review"] = [reason]
        if output_dir is not None:
            state["learning_status"] = "recorded"
            state["learning_summary_text"] = ""
            state["learning_record"] = {
                "requirement_identifier": state.get("requirement_identifier", ""),
                "requirement_name": state.get("requirement_name", ""),
                "mode": "not selected",
                "status": "blocked",
                "outcome": "blocked",
                "review_status": "not reviewed",
                "review_notes": reason,
                "failure_classification": [],
            }
            state["learning_artifacts"] = {}
            state["learning_store_path"] = str(output_dir / "learning")
        return state
