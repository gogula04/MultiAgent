from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import yaml_compat as yaml

from ..core import BaseStageAgent, normalize_term
from ..validators import validate_contract


class ArtifactAgentBase(BaseStageAgent):
    def _ensure_direct_dictionary(self, component_name: str) -> None:
        csv_path = self.runtime.procedure_data_dir / "uut_dictionary.csv"
        yaml_path = self.runtime.procedure_data_dir / "uut_dictionary.yaml"
        if csv_path.exists() and component_name in csv_path.read_text(errors="ignore"):
            return
        header = ["uut name", "rate", "initFcn", "return", "step fcn", "return_stepfn", "mockFcns", "preconditions comma sep"]
        row = [component_name, "0.005", "", "void", component_name, "void", "", ""]
        yaml_entry = {"uut_name": component_name, "rate": "0.005", "init_fcn": "", "step_fcn": component_name, "step_fcn_return": "void", "mock_fcns": [], "preconditions": []}
        self.runtime.append_csv_row(csv_path, header, row)
        self.runtime.append_yaml_entry(yaml_path, yaml_entry)

    def _append_missing_data_entries(self, result: Dict[str, object]) -> Tuple[List[str], List[str]]:
        missing_inputs = result.get("data_dictionary_findings", {}).get("inputs_not_found", [])
        missing_outputs = result.get("data_dictionary_findings", {}).get("outputs_not_found", [])
        for term in missing_inputs:
            self.runtime.append_data_dictionary(term, result, "argument")
        for term in missing_outputs:
            self.runtime.append_data_dictionary(term, result, "return")
        return missing_inputs, missing_outputs


class DirectArtifactAgent(ArtifactAgentBase):
    name = "Direct Artifact Agent"
    stage = "06_direct_artifacts"

    def run(self, result: Dict[str, object], decision: Dict[str, object]) -> Dict[str, object]:
        component_name = result.get("component_name") or result["requirement_id"]
        self._ensure_direct_dictionary(component_name)
        missing_inputs, missing_outputs = self._append_missing_data_entries(result)
        self.evaluator.load_source_terms()
        source_constants = getattr(self.evaluator, "source_constants", [])
        source_constraints = getattr(self.evaluator, "source_constraints", [])
        result = dict(result)
        result["source_constants"] = source_constants
        result["source_constraints"] = source_constraints
        rbtca_content, _ = self.evaluator.generate_rbtca_yaml(result, result["requirement_id"])
        rbtca_file = self.runtime.rbtca_dir / f"{result['requirement_id']}.yaml"
        self.runtime.write_text(rbtca_file, yaml.safe_dump(rbtca_content, sort_keys=False))
        test_content = self.evaluator.generate_test_case_file(result, result["requirement_id"], result["requirement_text"], component_name, fixture_component=component_name)
        test_file = self.runtime.test_cases_dir / f"test_{result['requirement_id']}.py"
        self.runtime.write_text(test_file, test_content)
        payload = {
            "requirement_id": result["requirement_id"],
            "selected_method": "direct",
            "files_created": [str(rbtca_file), str(test_file)],
            "files_updated": [str(self.runtime.procedure_data_dir / "data_dictionary.csv"), str(self.runtime.procedure_data_dir / "data_dictionary.yaml"), str(self.runtime.procedure_data_dir / "uut_dictionary.csv"), str(self.runtime.procedure_data_dir / "uut_dictionary.yaml")],
            "status": "completed",
            "rbtca_file": str(rbtca_file),
            "test_file": str(test_file),
            "source_constants": source_constants,
            "source_constraints": source_constraints,
            "missing_inputs": missing_inputs,
            "missing_outputs": missing_outputs,
        }
        validate_contract("artifact_patch", payload)
        self.emit("completed", payload, next_agent="traceability")
        return payload


class HybridArtifactAgent(ArtifactAgentBase):
    name = "Hybrid Artifact Agent"
    stage = "06_hybrid_artifacts"

    def run(self, result: Dict[str, object], decision: Dict[str, object]) -> Dict[str, object]:
        missing_inputs, missing_outputs = self._append_missing_data_entries(result)
        self.evaluator.load_source_terms()
        source_constants = getattr(self.evaluator, "source_constants", [])
        source_constraints = getattr(self.evaluator, "source_constraints", [])
        rvstest_file = self.runtime.build_rvstest(result, result["requirement_id"], result.get("component_name") or result["requirement_id"])
        rbtca_content, _ = self.evaluator.generate_rbtca_yaml(result, result["requirement_id"])
        rbtca_file = self.runtime.rbtca_dir / f"{result['requirement_id']}.yaml"
        self.runtime.write_text(rbtca_file, yaml.safe_dump(rbtca_content, sort_keys=False))
        test_content = self.evaluator.generate_test_case_file(result, result["requirement_id"], result["requirement_text"], result.get("component_name"), fixture_component=self.runtime.relative_path(rvstest_file))
        test_file = self.runtime.test_cases_dir / f"test_{result['requirement_id']}.py"
        self.runtime.write_text(test_file, test_content)
        payload = {
            "requirement_id": result["requirement_id"],
            "selected_method": "hybrid",
            "files_created": [str(rvstest_file), str(rbtca_file), str(test_file)],
            "files_updated": [str(self.runtime.procedure_data_dir / "data_dictionary.csv"), str(self.runtime.procedure_data_dir / "data_dictionary.yaml")],
            "status": "completed",
            "rbtca_file": str(rbtca_file),
            "test_file": str(test_file),
            "rvstest_file": str(rvstest_file),
            "source_constants": source_constants,
            "source_constraints": source_constraints,
            "missing_inputs": missing_inputs,
            "missing_outputs": missing_outputs,
        }
        validate_contract("artifact_patch", payload)
        self.emit("completed", payload, next_agent="traceability")
        return payload
