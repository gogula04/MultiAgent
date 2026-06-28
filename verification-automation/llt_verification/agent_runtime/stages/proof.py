from __future__ import annotations

from typing import Dict

from ..core import BaseStageAgent
from ..validators import validate_contract


class ProofAgent(BaseStageAgent):
    name = "Proof Agent"
    stage = "11_proof"

    def run(self, requirement_package: Dict[str, object], evidence_package: Dict[str, object], normalization_package: Dict[str, object], analysis_package: Dict[str, object], decision: Dict[str, object], artifacts: Dict[str, object], traceability: Dict[str, object], execution_result: Dict[str, object], debug_result: Dict[str, object], review_result: Dict[str, object]) -> Dict[str, object]:
        execution_status = execution_result.get("status")
        if review_result.get("status") == "approved" and execution_status == "passed" and traceability.get("passed"):
            status = "passed"
        elif review_result.get("status") == "approved" and execution_status == "dry_run" and traceability.get("passed"):
            status = "dry_run"
        else:
            status = "blocked"
        json_path = self.state.run_dir / "11_proof_report.json"
        md_path = self.state.run_dir / "11_proof_report.md"
        audit_path = self.state.run_dir / "00_audit_log.json"
        generated_files = list(self.runtime.generated_files) + [str(json_path), str(md_path), str(audit_path)]
        method_proof_status = "available" if decision.get("proof_table") else "not generated"
        branch_note = decision.get("branch_note") or f"{decision.get('selected_method', 'unknown').title()} selected."
        alias_trace = normalization_package.get("aliases", {}) if isinstance(normalization_package, dict) else {}
        extraction_aliases = requirement_package.get("extraction_contract", {}).get("aliases", {}) if isinstance(requirement_package.get("extraction_contract", {}), dict) else {}
        reuse_candidates = analysis_package.get("reuse_candidates", []) if isinstance(analysis_package, dict) else []
        report = {"requirement_id": requirement_package["requirement_id"], "status": status, "rendered_summary": f"Method proof: {method_proof_status}", "branch_note": branch_note, "alias_trace": alias_trace, "extraction_aliases": extraction_aliases, "reuse_candidates": reuse_candidates, "requirement": requirement_package, "evidence": evidence_package, "normalized_terms": normalization_package, "analysis": analysis_package, "method_decision": decision, "method_proof": decision.get("proof_table", []), "artifacts": artifacts, "traceability": traceability, "execution_result": execution_result, "debug_result": debug_result, "review": review_result, "generated_files": generated_files, "logs": self.state.logs, "pipeline_stages": self.state.stage_order, "policy": self.state.policy, "run_manifest": self.state.run_manifest}
        validate_contract("proof_report", report)
        self.emit(status, report, next_agent=None)
        try:
            learning_result = self.runtime.learning.record_approved_case(report)
        except Exception as exc:
            self.state.log(f"Learning update failed: {exc}", level="WARN")
            learning_result = {"status": "error", "reason": str(exc), "files_created": [], "files_updated": []}
        report["learning_result"] = learning_result
        if learning_result.get("status") == "created":
            generated_files.extend(learning_result.get("files_created", []))
            report["generated_files"] = generated_files
        json_path = self.state.write_json("11_proof_report.json", report)
        md_path = self.state.write_text("11_proof_report.md", self.runtime.support.render_report_markdown(report))
        self.runtime.generated_files.extend([str(json_path), str(md_path)])
        audit_path = self.state.write_json(
            "00_audit_log.json",
            {
                "requirement_id": requirement_package["requirement_id"],
                "branch_note": branch_note,
                "alias_trace": alias_trace,
                "extraction_aliases": extraction_aliases,
                "reuse_candidates": reuse_candidates,
                "method_decision": decision,
                "method_proof": decision.get("proof_table", []),
                "learning_result": learning_result,
                "policy": self.state.policy,
                "run_manifest": self.state.run_manifest,
                "stage_order": self.state.stage_order,
                "logs": self.state.logs,
                "audit_events": self.state.audit_events,
            },
        )
        self.runtime.generated_files.append(str(audit_path))
        return report
