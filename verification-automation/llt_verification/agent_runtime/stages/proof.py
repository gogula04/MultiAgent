from __future__ import annotations

from typing import Dict

from ..core import BaseStageAgent
from ..validators import validate_contract


class ProofAgent(BaseStageAgent):
    name = "Proof Agent"
    stage = "11_proof"

    def run(self, requirement_package: Dict[str, object], evidence_package: Dict[str, object], normalization_package: Dict[str, object], analysis_package: Dict[str, object], decision: Dict[str, object], artifacts: Dict[str, object], traceability: Dict[str, object], execution_result: Dict[str, object], debug_result: Dict[str, object], review_result: Dict[str, object]) -> Dict[str, object]:
        status = "passed" if review_result.get("status") == "approved" and execution_result.get("status") in {"passed", "dry_run"} and traceability.get("passed") else "blocked"
        report = {"requirement_id": requirement_package["requirement_id"], "status": status, "requirement": requirement_package, "evidence": evidence_package, "normalized_terms": normalization_package, "analysis": analysis_package, "method_decision": decision, "artifacts": artifacts, "traceability": traceability, "execution_result": execution_result, "debug_result": debug_result, "review": review_result, "generated_files": self.runtime.generated_files, "logs": self.state.logs, "pipeline_stages": self.state.stage_order}
        validate_contract("proof_report", report)
        self.emit(status, report, next_agent=None)
        json_path = self.state.write_json("11_proof_report.json", report)
        md_path = self.state.write_text("11_proof_report.md", self.runtime.support.render_report_markdown(report))
        self.runtime.generated_files.extend([str(json_path), str(md_path)])
        return report
