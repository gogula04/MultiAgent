from __future__ import annotations

from typing import Dict

from ..core import BaseStageAgent
from ..validators import validate_contract


class RepoEvidenceAgent(BaseStageAgent):
    name = "Repo Evidence Agent"
    stage = "02_repo_evidence"

    def run(self, requirement_package: Dict[str, object]) -> Dict[str, object]:
        evidence = self.evaluator.evaluate(requirement_package["requirement_text"], allow_source_reading=False)
        evidence["requirement_id"] = requirement_package["requirement_id"]
        evidence["component_name"] = requirement_package.get("component_name")
        evidence["requirement_file"] = requirement_package.get("requirement_file")
        payload = {
            "requirement_id": requirement_package["requirement_id"],
            "classification": evidence["classification"],
            "inputs": evidence["inputs"],
            "outputs": evidence["outputs"],
            "testable": evidence["testable"],
            "expressions": evidence["expressions"],
            "constants": evidence["constants"],
            "robustness_cases": evidence["robustness_cases"],
            "data_dictionary_findings": evidence["data_dictionary_findings"],
            "source_file_findings": evidence["source_file_findings"],
            "uut_dictionary_findings": evidence["uut_dictionary_findings"],
            "testability_analysis": evidence["testability_analysis"],
            "bold_terms": evidence["bold_terms"],
            "component_name": evidence.get("component_name"),
            "status": "completed",
        }
        validate_contract("evidence_package", payload)
        self.emit("completed", payload, evidence=evidence, next_agent="term_normalization")
        return payload
