from __future__ import annotations

from typing import Dict, List, Optional


class RequirementMethodMixin:
    def check_repo_pattern(self, component_name: str = None) -> Dict:
        evidence = {"pattern": "unknown", "confidence": 0.0, "evidence": {}}
        rvstest_files = []
        for vectors_dir in self.procedure_vectors_dirs:
            rvstest_files.extend(vectors_dir.rglob("*.rvstest"))
        evidence["evidence"]["rvstest_count"] = len(rvstest_files)
        direct_test_count = 0
        hybrid_test_count = 0
        for test_dir in self.test_cases_dirs:
            for test_file in test_dir.rglob("test_*.py"):
                try:
                    content = test_file.read_text(errors="ignore")
                except Exception:
                    continue
                if ".rvstest" in content:
                    hybrid_test_count += 1
                else:
                    direct_test_count += 1
        evidence["evidence"]["hybrid_test_count"] = hybrid_test_count
        evidence["evidence"]["direct_test_count"] = direct_test_count
        if component_name:
            component_lower = component_name.lower()
            matching_uut_entries = [info for uut_name, info in self.uut_dict_terms.items() if component_lower in uut_name or uut_name in component_lower]
            evidence["evidence"]["component_in_uut_dict"] = bool(matching_uut_entries)
            evidence["evidence"]["matching_uut_entries"] = matching_uut_entries[:5]
            evidence["evidence"]["component_is_complex"] = any(kw in component_lower for kw in ["queue", "crc", "struct", "pointer", "state"])
        if hybrid_test_count > 0:
            evidence["pattern"] = "hybrid"
            evidence["confidence"] = 0.6
        elif direct_test_count > 0:
            evidence["pattern"] = "direct"
            evidence["confidence"] = 0.6
        return evidence

    def _has_complex_requirement_signals(self, result: Dict) -> bool:
        inputs = [str(item).lower() for item in result.get("inputs", [])]
        outputs = [str(item).lower() for item in result.get("outputs", [])]
        expressions = result.get("expressions", {})
        types_and_ranges = result.get("types_and_ranges", [])
        complex_tokens = {"struct", "array", "pointer", "queue", "buffer", "memory", "handle", "context", "instance", "reference", "rvstest", "procedure-vector"}
        if any(any(token in name for token in complex_tokens) for name in inputs + outputs):
            return True
        if len(expressions.get("conditions", [])) > 2:
            return True
        for item in types_and_ranges:
            if not isinstance(item, dict):
                continue
            text = " ".join(
                str(item.get(key, "")).lower()
                for key in ("name", "type", "role", "section", "data_source", "min", "max", "default")
            )
            if any(token in text for token in complex_tokens):
                return True
        return False

    def _uut_evidence_summary(self, result: Dict, component_name: Optional[str] = None) -> Dict[str, object]:
        uut_findings = result.get("uut_dictionary_findings", {}) or {}
        matches = uut_findings.get("matches", {}) or {}
        component_matches: List[Dict[str, object]] = []
        component_key = (component_name or "").lower()
        if component_key:
            component_matches = list(matches.get(component_name, []))
            if not component_matches:
                for term, items in matches.items():
                    if component_key in str(term).lower() or str(term).lower() in component_key:
                        component_matches.extend(items if isinstance(items, list) else [items])
        selected_entry = component_matches[0]["details"] if component_matches and isinstance(component_matches[0], dict) and "details" in component_matches[0] else None
        if selected_entry is None and component_key:
            for uut_name, info in self.uut_dict_terms.items():
                if component_key in uut_name or uut_name in component_key:
                    selected_entry = info
                    break
        selected_entry = selected_entry or {}
        step_fcn = str(selected_entry.get("step_fcn") or selected_entry.get("stepFcn") or selected_entry.get("step fcn") or "").strip()
        init_fcn = str(selected_entry.get("init_fcn") or selected_entry.get("initFcn") or selected_entry.get("init fcn") or "").strip()
        mock_fcns = selected_entry.get("mock_fcns") or selected_entry.get("mockFcns") or []
        return {
            "component_name": component_name,
            "has_uut_match": bool(component_matches or selected_entry),
            "uut_entry": selected_entry,
            "step_function": step_fcn,
            "init_function": init_fcn,
            "has_step_function": bool(step_fcn),
            "has_init_function": bool(init_fcn),
            "at_most_one_init": not bool(init_fcn) or isinstance(init_fcn, str),
            "mock_functions": mock_fcns if isinstance(mock_fcns, list) else [mock_fcns],
            "candidates": component_matches,
        }

    def _decision_proof_table(self, result: Dict, component_name: Optional[str], uut_analysis: Dict) -> List[Dict[str, str]]:
        complex_signal = self._has_complex_requirement_signals(result)
        has_inputs = bool(result.get("inputs"))
        has_outputs = bool(result.get("outputs"))
        direct_selected = uut_analysis.get("recommended_method") == "direct"
        hybrid_selected = uut_analysis.get("recommended_method") == "hybrid"
        blocked_selected = uut_analysis.get("recommended_method") == "unknown" or uut_analysis.get("blocked")
        direct_proof = []
        if has_inputs or has_outputs:
            direct_proof.append("Requirement has input/output evidence")
        if uut_analysis.get("criteria", {}).get("single_step_function"):
            direct_proof.append("UUT dictionary proves a single step function")
        if uut_analysis.get("criteria", {}).get("at_most_one_init"):
            direct_proof.append("UUT dictionary shows at most one init routine")
        if uut_analysis.get("criteria", {}).get("normal_data_flow"):
            direct_proof.append("Requirement flow is normal, not multi-step orchestration")
        if not direct_proof:
            direct_proof.append("Direct evidence is incomplete")
        hybrid_proof = []
        if complex_signal:
            hybrid_proof.append("Requirement evidence indicates complex data handling or procedure-vector behavior")
        if uut_analysis.get("criteria", {}).get("requires_rvstest"):
            hybrid_proof.append(".rvstest behavior is required or implied")
        if not hybrid_proof:
            hybrid_proof.append("No complex-data or procedure-vector evidence was proven")
        block_proof = uut_analysis.get("reasons", []) or ["Insufficient evidence to prove Direct or Hybrid safely"]
        return [
            {
                "branch": "Direct",
                "verdict": "selected" if direct_selected else "rejected",
                "proof": "; ".join(direct_proof),
                "evidence": "safe" if direct_selected else "not enough to select Direct",
            },
            {
                "branch": "Hybrid",
                "verdict": "selected" if hybrid_selected else "rejected",
                "proof": "; ".join(hybrid_proof),
                "evidence": "safe" if hybrid_selected else "not enough to select Hybrid",
            },
            {
                "branch": "Blocked",
                "verdict": "selected" if blocked_selected else "not selected",
                "proof": "; ".join(block_proof),
                "evidence": "safe" if blocked_selected else "branch remains available if evidence changes",
            },
        ]

    def analyze_uut_for_method_decision(self, result: Dict, component_name: Optional[str] = None) -> Dict:
        analysis = {
            "recommended_method": "unknown",
            "reasons": [],
            "criteria": {
                "single_step_function": False,
                "at_most_one_init": False,
                "normal_data_flow": True,
                "complex_data_types": False,
                "requires_rvstest": False,
            },
            "blocked": False,
        }
        inputs = result.get("inputs", [])
        outputs = result.get("outputs", [])
        expressions = result.get("expressions", {})
        uut_evidence = self._uut_evidence_summary(result, component_name)
        if not inputs and not outputs:
            analysis["blocked"] = True
            analysis["reasons"].append("No input/output variables identified")
        if not uut_evidence.get("has_uut_match"):
            analysis["blocked"] = True
            analysis["reasons"].append("No UUT dictionary match for the component")
        if not uut_evidence.get("has_step_function"):
            analysis["blocked"] = True
            analysis["reasons"].append("UUT dictionary entry is missing a step function")
        if uut_evidence.get("has_init_function") and not uut_evidence.get("at_most_one_init"):
            analysis["blocked"] = True
            analysis["reasons"].append("UUT dictionary entry has more than one init routine")
        if self._has_complex_requirement_signals(result):
            analysis["criteria"]["complex_data_types"] = True
            analysis["reasons"].append("Requirement evidence indicates complex data handling or procedure-vector behavior")
        if len(expressions.get("conditions", [])) > 2:
            analysis["criteria"]["normal_data_flow"] = False
            analysis["reasons"].append("Multiple conditions indicate complex control flow")
        if analysis["criteria"]["complex_data_types"]:
            analysis["recommended_method"] = "hybrid"
            analysis["criteria"]["requires_rvstest"] = True
            analysis["reasons"].append("Hybrid evidence present in requirement or type signals")
        elif uut_evidence.get("has_step_function") and uut_evidence.get("at_most_one_init") and analysis["criteria"]["normal_data_flow"] and (inputs or outputs):
            analysis["recommended_method"] = "direct"
            analysis["criteria"]["single_step_function"] = True
            analysis["criteria"]["at_most_one_init"] = True
            analysis["reasons"].append("Direct evidence present in UUT dictionary and requirement flow")
        else:
            if not analysis["blocked"]:
                analysis["blocked"] = True
                analysis["reasons"].append("Insufficient evidence to prove a safe Direct or Hybrid choice")
        if str(uut_evidence.get("step_function", "")).lower().find("rvstest") >= 0:
            analysis["criteria"]["requires_rvstest"] = True
        return analysis

    def make_method_decision(self, result: Dict, component_name: str = None) -> Dict:
        uut_analysis = self.analyze_uut_for_method_decision(result, component_name)
        evidence_citations = {
            "data_dictionary": result.get("data_dictionary_findings", {}),
            "source_file": result.get("source_file_findings", {}),
            "uut_dictionary": result.get("uut_dictionary_findings", {}),
            "retrieval_summary": result.get("retrieval_summary", {}),
        }
        proof_table = self._decision_proof_table(result, component_name, uut_analysis)
        decision = {
            "selected_method": "unknown",
            "reason": "",
            "evidence": {"uut_analysis": uut_analysis, "citations": evidence_citations},
            "proof_table": proof_table,
            "rejected_modes": {},
        }
        if not result.get("testable", False):
            decision["selected_method"] = "blocked"
            blockers = result.get("testability_analysis", {}).get("blockers", [])
            decision["reason"] = "Blocked: requirement is not testable from the available evidence" + (f" ({'; '.join(blockers)})" if blockers else "")
            return decision
        if uut_analysis.get("blocked"):
            decision["selected_method"] = "blocked"
            decision["reason"] = "Blocked: " + "; ".join(uut_analysis["reasons"])
            return decision
        if uut_analysis["criteria"]["complex_data_types"] or uut_analysis["criteria"]["requires_rvstest"]:
            decision["selected_method"] = "hybrid"
            decision["reason"] = f"Hybrid selected from evidence ({'; '.join(uut_analysis['reasons'])})"
            decision["rejected_modes"]["direct"] = "Requirement evidence proves complex data handling, rvstest behavior, or non-linear setup"
        elif uut_analysis["criteria"]["single_step_function"] and uut_analysis["criteria"]["at_most_one_init"] and uut_analysis["criteria"]["normal_data_flow"]:
            decision["selected_method"] = "direct"
            decision["reason"] = f"Direct selected from evidence ({'; '.join(uut_analysis['reasons'])})"
            decision["rejected_modes"]["hybrid"] = "Hybrid indicators are absent or not required by the evidence"
        else:
            decision["selected_method"] = "blocked"
            decision["reason"] = "Blocked: insufficient evidence for a safe Direct or Hybrid choice"
        return decision
