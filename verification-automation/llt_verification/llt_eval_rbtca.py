from __future__ import annotations

from typing import Dict, Optional, Tuple


class RequirementRBTCAMixin:
    def _map_to_rbtca_type(self, term_type: str) -> str:
        t = term_type.lower()
        if t in ["float", "double", "real"]:
            return "Float"
        if t in ["int", "integer", "int32", "int64", "uint32", "uint64"]:
            return "Integer"
        if t in ["bool", "boolean"]:
            return "Boolean"
        if t in ["enum", "enumeration"]:
            return "Enumeration"
        if t in ["string", "char", "char*"]:
            return "String"
        if t == "array":
            return "Array"
        if t in ["struct", "composite"]:
            return "Composite"
        return "Float"

    def generate_rbtca_yaml(self, result: Dict, req_id: str, branch_note: Optional[str] = None) -> Tuple[Dict, Dict]:
        rbtca = {
            "metadata": {
                "requirement_id": req_id,
                "selected_method": result.get("selected_method"),
            },
            "inputs": {},
            "summary": {"covered_cases": 0, "required_cases": 0, "missing": []},
        }
        if branch_note:
            rbtca["metadata"]["branch_note"] = branch_note
            rbtca["summary"]["branch_note"] = branch_note
        reuse_candidates = result.get("learning_reuse_candidates", []) or []
        if reuse_candidates:
            rbtca["metadata"]["learning_reuse_candidates"] = [
                {
                    "case_id": item.get("case_id"),
                    "requirement_id": item.get("requirement_id"),
                    "selected_method": item.get("selected_method"),
                    "score": item.get("score"),
                    "matched_terms": item.get("matched_terms", []),
                }
                for item in reuse_candidates
                if isinstance(item, dict)
            ]
        test_case_map = {"inputs": {}, "logic": {}, "math": {}}
        inputs = result.get("inputs", [])
        expressions = result.get("expressions", {})
        tc_counter = 1
        primary_input = inputs[0] if inputs else None
        if primary_input:
            term_info = self.get_term_info(primary_input)
            sample_values = self._sample_values_for_term(primary_input, term_info)
            source_candidates = self.get_source_value_candidates(primary_input)
            source_evidence = self.get_source_evidence_for_term(primary_input)
            if source_candidates:
                sample_values["nominal"] = source_candidates[0]
            rbtca_type = self._map_to_rbtca_type(term_info.get("type", "unknown") if term_info else "unknown")
            entry = {"name": primary_input, "type": rbtca_type}
            if source_candidates:
                entry["source_values"] = source_candidates
            if source_evidence.get("constraints"):
                entry["source_constraints"] = [item.get("expression") for item in source_evidence["constraints"] if item.get("expression")]
            if rbtca_type == "Boolean":
                entry["range"] = {"T": f"test_{req_id}.py:TC{tc_counter:03d}", "F": f"test_{req_id}.py:TC{tc_counter + 1:03d}"}
                test_case_map["inputs"][primary_input] = [(f"TC{tc_counter:03d}", "Boolean TRUE case", {"value": sample_values.get("true", True)}), (f"TC{tc_counter + 1:03d}", "Boolean FALSE case", {"value": sample_values.get("false", False)})]
                tc_counter += 2
            elif rbtca_type == "Enumeration":
                valid_values = sample_values.get("valid_values") or [sample_values.get("nominal", "VALID")]
                entry["values"] = valid_values
                entry["invalid"] = sample_values.get("invalid", "__INVALID__")
                test_case_map["inputs"][primary_input] = []
                for value in valid_values:
                    test_case_map["inputs"][primary_input].append((f"TC{tc_counter:03d}", f"Enumeration valid value {value}", {"value": value}))
                    tc_counter += 1
                entry["range"] = {"values": f"test_{req_id}.py:TC001"}
            elif rbtca_type in ["Integer", "Float"]:
                entry["range"] = {"maximum": f"test_{req_id}.py:TC{tc_counter:03d}", "minimum": f"test_{req_id}.py:TC{tc_counter + 1:03d}"}
                entry["robustness"] = {"above-max": f"test_{req_id}.py:TC{tc_counter + 2:03d}", "below-min": f"test_{req_id}.py:TC{tc_counter + 3:03d}", "zero": f"test_{req_id}.py:TC{tc_counter + 4:03d}"}
                test_case_map["inputs"][primary_input] = [(f"TC{tc_counter:03d}", "Input robustness below minimum", {}), (f"TC{tc_counter + 1:03d}", "Input boundary equal minimum", {}), (f"TC{tc_counter + 2:03d}", "Input independence test", {}), (f"TC{tc_counter + 3:03d}", "Input robustness zero", {}), (f"TC{tc_counter + 4:03d}", "Input robustness above maximum", {})]
                tc_counter += 5
            else:
                entry["range"] = {"nominal": f"test_{req_id}.py:TC{tc_counter:03d}", "alternate": f"test_{req_id}.py:TC{tc_counter + 1:03d}"}
                test_case_map["inputs"][primary_input] = [(f"TC{tc_counter:03d}", "Nominal input case", {"value": sample_values.get("nominal", 1)}), (f"TC{tc_counter + 1:03d}", "Alternate input case", {"value": sample_values.get("invalid", sample_values.get("nominal", 1))})]
                tc_counter += 2
            rbtca["inputs"]["A"] = entry
        for expr in list(set(expressions.get("conditions", []) + expressions.get("comparisons", []))):
            rbtca.setdefault("logic", {})
            rbtca["logic"][f"EX{len(rbtca['logic']) + 1}"] = {"expression": expr, "conditions": [{"condition": expr, "independence": {"T": f"test_{req_id}.py:TC{tc_counter:03d}", "F": f"test_{req_id}.py:TC{tc_counter + 1:03d}"}, "boundary": {"lesser": f"test_{req_id}.py:TC{tc_counter:03d}", "equal": f"test_{req_id}.py:TC{tc_counter + 1:03d}", "greater": f"test_{req_id}.py:TC{tc_counter + 2:03d}"}}]}
            test_case_map["logic"][expr] = [(f"TC{tc_counter:03d}", "Condition TRUE/boundary lesser", {}), (f"TC{tc_counter + 1:03d}", "Condition FALSE/boundary equal", {}), (f"TC{tc_counter + 2:03d}", "Condition TRUE/boundary greater", {})]
            tc_counter += 3
        for calc in expressions.get("calculations", []):
            rbtca.setdefault("math", []).append({"expression": calc, "underflow": f"test_{req_id}.py:TC{tc_counter:03d}", "overflow": f"test_{req_id}.py:TC{tc_counter + 1:03d}"})
            test_case_map["math"][calc] = [(f"TC{tc_counter:03d}", "Math underflow case", {}), (f"TC{tc_counter + 1:03d}", "Math overflow case", {})]
            tc_counter += 2
        rbtca["summary"]["required_cases"] = tc_counter - 1
        rbtca["summary"]["covered_cases"] = tc_counter - 1
        return rbtca, test_case_map
