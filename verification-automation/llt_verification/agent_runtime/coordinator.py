"""Peer-agent coordinator for LLT verification."""

from __future__ import annotations

import json
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from llt_evaluator import RequirementEvaluator
from scripts.workspace_utils import candidate_dirs, detect_workspace_root

from .core import StageContext
from .policy import VerificationPolicy
from .learning import LearningStore
from .poolside import PoolsideClient, poolside_from_env
from .state import VerificationRunState
from .stages import (
    DebugAgent,
    DirectArtifactAgent,
    ExecutionAgent,
    HybridArtifactAgent,
    PoolsideAnalysisAgent,
    ProofAgent,
    RepoEvidenceAgent,
    RequirementAgent,
    ReviewerAgent,
    StrategyAgent,
    TermNormalizationAgent,
    TraceabilityAgent,
)
from .support import ArtifactSupport


class VerificationCoordinator:
    def __init__(
        self,
        workspace_root: Optional[str] = None,
        poolside_client: Optional[PoolsideClient] = None,
        dry_run: bool = False,
        continue_on_failure: bool = False,
        allow_implementation_reads: Optional[bool] = None,
        auto_learning_approved: Optional[bool] = None,
        tenant_id: Optional[str] = None,
        user_role: Optional[str] = None,
    ):
        self.workspace_root = detect_workspace_root(workspace_root)
        self.poolside_client = poolside_client or poolside_from_env()
        self.dry_run = dry_run
        self.continue_on_failure = continue_on_failure
        self.policy = VerificationPolicy.from_env(allow_implementation_reads, auto_learning_approved, tenant_id=tenant_id, user_role=user_role)
        self.evaluator = RequirementEvaluator(str(self.workspace_root))
        self.procedure_data_dir = self.workspace_root / "verification" / "test-procedures" / "procedure-data"
        self.test_cases_dir = self.workspace_root / "verification" / "test-cases" / "low_level"
        self.rbtca_dir = self.workspace_root / "records" / "rbtca" / "low_level"
        self.procedure_vectors_dir = self.workspace_root / "verification" / "test-procedures" / "procedure-vectors"
        self.outputs_dir = self.workspace_root / "outputs" / "runs"
        self.source_dirs = candidate_dirs(self.workspace_root, [("software", "source"), ("source",), ("src",)], fallback_to_root=False)
        self.generated_files: List[str] = []
        self.support = ArtifactSupport(self)
        self.learning = LearningStore(self)

    def relative_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.workspace_root))
        except Exception:
            return str(path)

    def write_text(self, path: Path, content: str) -> None:
        self.support.write_text(path, content)

    def append_csv_row(self, path: Path, header: List[str], row: List[object]) -> None:
        self.support.append_csv_row(path, header, row)

    def append_yaml_entry(self, path: Path, entry: Dict[str, object]) -> None:
        self.support.append_yaml_entry(path, entry)

    def append_data_dictionary(self, term: str, result: Dict[str, object], element_type: str = "argument") -> None:
        self.support.append_data_dictionary(term, result, element_type)

    def build_rvstest(self, result: Dict[str, object], req_id: str, component_name: str):
        return self.support.build_rvstest(result, req_id, component_name)

    def run_pytest(self, test_file: Path, requirement_id: Optional[str] = None) -> Dict[str, object]:
        return self.support.run_pytest(test_file, requirement_id)

    def render_report_markdown(self, report: Dict[str, object]) -> str:
        return self.support.render_report_markdown(report)

    def _blocked_review_result(self, req_id: str, reason: str, execution_result: Dict[str, object], debug_result: Dict[str, object]) -> Dict[str, object]:
        issues = [reason] if reason else ["Auto-repair could not produce a passing test run."]
        if execution_result.get("status") and execution_result.get("status") != "passed":
            issues.append(f"initial execution status: {execution_result.get('status')}")
        if debug_result.get("status") and debug_result.get("status") not in {"passed", "skipped", "not_run", "dry_run"}:
            issues.append(f"debug status: {debug_result.get('status')}")
        return {
            "requirement_id": req_id,
            "status": "rejected",
            "summary": reason or "Auto-repair blocked the requirement.",
            "issues": issues,
            "recommendations": [
                "Inspect the failing evidence and adjust the generated test or dictionary entries.",
                "If implementation-code access is needed, request exception approval before retrying.",
            ],
        }

    def _stage_context(self, state: VerificationRunState) -> StageContext:
        return StageContext(runtime=self, state=state, evaluator=self.evaluator, poolside_client=self.poolside_client, policy=self.policy)

    def run(self, requirement: str) -> Dict[str, object]:
        self.generated_files = []
        req_id_match = re.search(r"FAF-LLR-\d+", requirement)
        req_id = req_id_match.group(0) if req_id_match else re.sub(r"[^A-Za-z0-9]+", "_", requirement).lower()[:40] or "generated"
        tenant_scope = self.policy.tenant_scope_path()
        run_dir = self.outputs_dir / tenant_scope / req_id / re.sub(r"[^A-Za-z0-9]+", "_", requirement).lower()[:24]
        state = VerificationRunState(self.workspace_root, requirement, req_id, run_dir, policy=self.policy.manifest())
        run_manifest = {
            "requirement_id": req_id,
            "requirement_prompt": requirement,
            "workspace_root": str(self.workspace_root),
            "policy": self.policy.manifest(),
            "tenant_id": self.policy.normalized_tenant_id(),
            "user_role": self.policy.normalized_user_role(),
            "allowed_evidence_sources": list(self.policy.allowed_evidence_sources),
            "requirement_only_mode": self.policy.requirement_only_mode,
            "implementation_reads_approved": self.policy.implementation_reads_approved,
            "auto_learning_enabled": self.policy.auto_learning_allowed(),
        }
        state.run_manifest = run_manifest
        manifest_path = state.write_json("00_run_manifest.json", run_manifest)
        self.generated_files.append(str(manifest_path))
        state.log("Run manifest created")
        ctx = self._stage_context(state)
        req_agent = RequirementAgent(ctx)
        evidence_agent = RepoEvidenceAgent(ctx)
        normalization_agent = TermNormalizationAgent(ctx)
        analysis_agent = PoolsideAnalysisAgent(ctx)
        strategy_agent = StrategyAgent(ctx)
        direct_agent = DirectArtifactAgent(ctx)
        hybrid_agent = HybridArtifactAgent(ctx)
        traceability_agent = TraceabilityAgent(ctx)
        execution_agent = ExecutionAgent(ctx)
        debug_agent = DebugAgent(ctx)
        review_agent = ReviewerAgent(ctx)
        proof_agent = ProofAgent(ctx)
        requirement_package = req_agent.run(requirement)
        evidence_package = evidence_agent.run(requirement_package)
        normalization_package = normalization_agent.run(requirement_package, evidence_package)
        learning_candidates = self.learning.find_similar_cases(requirement_package, evidence_package, normalization_package)
        normalization_package["learning_candidates"] = learning_candidates
        analysis_package = analysis_agent.run(requirement_package, evidence_package, normalization_package)
        analysis_package["reuse_candidates"] = learning_candidates
        strategy_package = strategy_agent.run(requirement_package, evidence_package, analysis_package)
        if strategy_package["selected_method"] == "blocked":
            review_result = {"requirement_id": req_id, "status": "rejected", "summary": "Strategy agent blocked the requirement.", "issues": [strategy_package["reason"]], "recommendations": ["Resolve the evidence gap before retrying."]}
            review_agent.emit("rejected", review_result, next_agent="proof")
            return proof_agent.run(requirement_package, evidence_package, normalization_package, analysis_package, strategy_package, {"requirement_id": req_id, "selected_method": "blocked", "files_created": [], "files_updated": [], "status": "blocked"}, {"requirement_id": req_id, "passed": False, "issues": [strategy_package["reason"]], "status": "failed"}, {"requirement_id": req_id, "status": "not_run", "attempts": 0, "changes": [], "execution_result": {}}, review_result)
        artifacts = direct_agent.run(requirement_package, strategy_package) if strategy_package["selected_method"] == "direct" else hybrid_agent.run(requirement_package, strategy_package)
        if artifacts.get("status") == "blocked":
            blocked_reason = artifacts.get("blocked_reason") or "Artifact generation blocked due to insufficient evidence."
            traceability = {"requirement_id": req_id, "passed": False, "issues": [blocked_reason], "status": "failed"}
            execution_result = {"requirement_id": req_id, "status": "blocked", "command": "", "exit_code": None, "stdout": "", "stderr": blocked_reason}
            debug_result = {"requirement_id": req_id, "status": "blocked", "attempts": 0, "changes": [], "blocked_reason": blocked_reason, "evidence_backed": False, "execution_result": execution_result, "source_constants": [], "source_constraints": []}
            review_result = self._blocked_review_result(req_id, blocked_reason, execution_result, debug_result)
            review_agent.emit("rejected", review_result, next_agent="proof")
            return proof_agent.run(requirement_package, evidence_package, normalization_package, analysis_package, strategy_package, artifacts, traceability, execution_result, debug_result, review_result)
        traceability = traceability_agent.run(requirement_package, strategy_package, artifacts)
        execution_result = execution_agent.run(artifacts, strategy_package, dry_run=self.dry_run)
        debug_result = debug_agent.run(artifacts, execution_result, continue_on_failure=execution_result.get("status") != "passed")
        final_execution_result = debug_result.get("execution_result") if debug_result.get("status") in {"passed", "failed"} else execution_result
        if debug_result.get("status") in {"blocked", "not_run"} or final_execution_result.get("status") not in {"passed", "dry_run"}:
            blocked_reason = debug_result.get("blocked_reason") or final_execution_result.get("stderr") or final_execution_result.get("stdout") or "Auto-repair could not produce a passing test run."
            review_result = self._blocked_review_result(req_id, blocked_reason, execution_result, debug_result)
            review_agent.emit("rejected", review_result, next_agent="proof")
            return proof_agent.run(requirement_package, evidence_package, normalization_package, analysis_package, strategy_package, artifacts, traceability, final_execution_result, debug_result, review_result)
        review_result = review_agent.run(requirement_package, evidence_package, artifacts, final_execution_result, debug_result, strategy_package)
        return proof_agent.run(requirement_package, evidence_package, normalization_package, analysis_package, strategy_package, artifacts, traceability, final_execution_result, debug_result, review_result)


VerificationAgent = VerificationCoordinator


def run_verification_agent(
    requirement: str,
    workspace_root: Optional[str] = None,
    dry_run: bool = False,
    continue_on_failure: bool = False,
    allow_implementation_reads: bool = False,
    auto_learning_approved: Optional[bool] = None,
    tenant_id: Optional[str] = None,
    user_role: Optional[str] = None,
) -> Dict[str, object]:
    return VerificationCoordinator(
        workspace_root=workspace_root,
        dry_run=dry_run,
        continue_on_failure=continue_on_failure,
        allow_implementation_reads=allow_implementation_reads,
        auto_learning_approved=auto_learning_approved,
        tenant_id=tenant_id,
        user_role=user_role,
    ).run(requirement)
