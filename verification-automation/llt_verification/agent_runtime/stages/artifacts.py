from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import yaml_compat as yaml

from ..core import BaseStageAgent, normalize_term
from ..validators import validate_contract


class ArtifactAgentBase(BaseStageAgent):
    def _branch_note(self, decision: Dict[str, object]) -> str:
        selected_method = str(decision.get("selected_method") or "unknown").strip()
        reason = " ".join(str(decision.get("reason") or "").split())
        if reason:
            return f"{selected_method.title()} selected: {reason}"
        return f"{selected_method.title()} selected."

    def _ensure_direct_dictionary(self, result: Dict[str, object], component_name: str) -> None:
        csv_path = self.runtime.procedure_data_dir / "uut_dictionary.csv"
        yaml_path = self.runtime.procedure_data_dir / "uut_dictionary.yaml"
        if csv_path.exists() and component_name in csv_path.read_text(errors="ignore"):
            return
        uut_findings = result.get("uut_dictionary_findings", {}) if isinstance(result, dict) else {}
        matches = uut_findings.get("matches", {}) if isinstance(uut_findings, dict) else {}
        candidate_matches = matches.get(component_name, []) if isinstance(matches, dict) else []
        if not candidate_matches:
            lookup_entry = self.evaluator._lookup_uut_entry(component_name) if hasattr(self.evaluator, "_lookup_uut_entry") else None
            if isinstance(lookup_entry, dict):
                candidate_matches = [{"details": lookup_entry}]
        if not candidate_matches:
            raise ValueError(f"Direct method requires a proven UUT dictionary match for {component_name}")
        match_details = {}
        for candidate in candidate_matches:
            if isinstance(candidate, dict) and isinstance(candidate.get("details"), dict):
                match_details = candidate["details"]
                break
        if not match_details:
            raise ValueError(f"Direct method requires a structured UUT dictionary entry for {component_name}")
        canonical_name = str(match_details.get("uut_name") or match_details.get("name") or component_name).strip()
        if not canonical_name:
            raise ValueError(f"Direct method requires a valid UUT dictionary name for {component_name}")
        step_fcn = str(match_details.get("step_fcn") or match_details.get("stepFcn") or match_details.get("step fcn") or "").strip()
        if not step_fcn:
            raise ValueError(f"Direct method requires a proven step function for {component_name}")
        header = ["uut name", "rate", "initFcn", "return", "step fcn", "return_stepfn", "mockFcns", "preconditions comma sep"]
        row = [
            canonical_name,
            str(match_details.get("rate") or "0.005"),
            str(match_details.get("init_fcn") or match_details.get("initFcn") or ""),
            str(match_details.get("step_fcn_return") or match_details.get("return") or "void"),
            step_fcn,
            str(match_details.get("return_stepfn") or match_details.get("return_stepFn") or match_details.get("return_step_fcn") or match_details.get("step_fcn_return") or "void"),
            match_details.get("mock_fcns") or match_details.get("mockFcns") or [],
            match_details.get("preconditions") or match_details.get("preconditions comma sep") or [],
        ]
        yaml_entry = {
            "uut_name": canonical_name,
            "rate": row[1],
            "init_fcn": row[2],
            "step_fcn": row[4],
            "step_fcn_return": row[3],
            "mock_fcns": row[6] if isinstance(row[6], list) else [row[6]] if row[6] else [],
            "preconditions": row[7] if isinstance(row[7], list) else [row[7]] if row[7] else [],
        }
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
        branch_note = self._branch_note(decision)
        self._ensure_direct_dictionary(result, component_name)
        missing_inputs, missing_outputs = self._append_missing_data_entries(result)
        types_struct_file = self.runtime.support.append_types_struct(result)
        source_constants = []
        source_constraints = []
        if self.policy.implementation_access_allowed():
            self.evaluator.load_source_terms()
            source_constants = getattr(self.evaluator, "source_constants", [])
            source_constraints = getattr(self.evaluator, "source_constraints", [])
        else:
            self.state.log("Direct artifact generation skipped implementation/source reads due to policy")
        result = dict(result)
        result["source_constants"] = source_constants
        result["source_constraints"] = source_constraints
        result["selected_method"] = decision.get("selected_method")
        result["learning_reuse_candidates"] = decision.get("reuse_candidates", [])
        try:
            rbtca_content, _ = self.evaluator.generate_rbtca_yaml(result, result["requirement_id"], branch_note=branch_note)
            rbtca_file = self.runtime.rbtca_dir / f"{result['requirement_id']}.yaml"
            self.runtime.write_text(rbtca_file, yaml.safe_dump(rbtca_content, sort_keys=False))
            test_content = self.evaluator.generate_test_case_file(result, result["requirement_id"], result["requirement_text"], component_name, fixture_component=component_name, branch_note=branch_note)
            test_file = self.runtime.test_cases_dir / f"test_{result['requirement_id']}.py"
            self.runtime.write_text(test_file, test_content)
        except ValueError as exc:
            payload = {
                "requirement_id": result["requirement_id"],
                "selected_method": "blocked",
                "branch_note": branch_note,
                "files_created": [],
                "files_updated": [str(self.runtime.procedure_data_dir / "data_dictionary.csv"), str(self.runtime.procedure_data_dir / "data_dictionary.yaml"), str(self.runtime.procedure_data_dir / "uut_dictionary.csv"), str(self.runtime.procedure_data_dir / "uut_dictionary.yaml")] + ([str(types_struct_file)] if types_struct_file else []),
                "status": "blocked",
                "blocked_reason": str(exc),
                "rbtca_file": None,
                "test_file": None,
                "types_struct_file": str(types_struct_file) if types_struct_file else None,
                "source_constants": source_constants,
                "source_constraints": source_constraints,
                "missing_inputs": missing_inputs,
                "missing_outputs": missing_outputs,
            }
            validate_contract("artifact_patch", payload)
            self.emit("blocked", payload, next_agent="proof")
            return payload
        payload = {
            "requirement_id": result["requirement_id"],
            "selected_method": "direct",
            "branch_note": branch_note,
            "files_created": [str(rbtca_file), str(test_file)],
            "files_updated": [str(self.runtime.procedure_data_dir / "data_dictionary.csv"), str(self.runtime.procedure_data_dir / "data_dictionary.yaml"), str(self.runtime.procedure_data_dir / "uut_dictionary.csv"), str(self.runtime.procedure_data_dir / "uut_dictionary.yaml")] + ([str(types_struct_file)] if types_struct_file else []),
            "status": "completed",
            "rbtca_file": str(rbtca_file),
            "test_file": str(test_file),
            "types_struct_file": str(types_struct_file) if types_struct_file else None,
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
        branch_note = self._branch_note(decision)
        missing_inputs, missing_outputs = self._append_missing_data_entries(result)
        source_constants = []
        source_constraints = []
        if self.policy.implementation_access_allowed():
            self.evaluator.load_source_terms()
            source_constants = getattr(self.evaluator, "source_constants", [])
            source_constraints = getattr(self.evaluator, "source_constraints", [])
        else:
            self.state.log("Hybrid artifact generation skipped implementation/source reads due to policy")
        result = dict(result)
        result["selected_method"] = decision.get("selected_method")
        result["learning_reuse_candidates"] = decision.get("reuse_candidates", [])
        try:
            rvstest_file = self.runtime.build_rvstest(result, result["requirement_id"], result.get("component_name") or result["requirement_id"], branch_note=branch_note)
            rbtca_content, _ = self.evaluator.generate_rbtca_yaml(result, result["requirement_id"], branch_note=branch_note)
            rbtca_file = self.runtime.rbtca_dir / f"{result['requirement_id']}.yaml"
            self.runtime.write_text(rbtca_file, yaml.safe_dump(rbtca_content, sort_keys=False))
            test_content = self.evaluator.generate_test_case_file(result, result["requirement_id"], result["requirement_text"], result.get("component_name"), fixture_component=self.runtime.relative_path(rvstest_file), branch_note=branch_note)
            test_file = self.runtime.test_cases_dir / f"test_{result['requirement_id']}.py"
            self.runtime.write_text(test_file, test_content)
        except ValueError as exc:
            payload = {
                "requirement_id": result["requirement_id"],
                "selected_method": "blocked",
                "branch_note": branch_note,
                "files_created": [],
                "files_updated": [str(self.runtime.procedure_data_dir / "data_dictionary.csv"), str(self.runtime.procedure_data_dir / "data_dictionary.yaml")],
                "status": "blocked",
                "blocked_reason": str(exc),
                "rbtca_file": None,
                "test_file": None,
                "rvstest_file": None,
                "source_constants": source_constants,
                "source_constraints": source_constraints,
                "missing_inputs": missing_inputs,
                "missing_outputs": missing_outputs,
            }
            validate_contract("artifact_patch", payload)
            self.emit("blocked", payload, next_agent="proof")
            return payload
        payload = {
            "requirement_id": result["requirement_id"],
            "selected_method": "hybrid",
            "branch_note": branch_note,
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
