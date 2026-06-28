from __future__ import annotations

from typing import Dict, Optional


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
        for name in inputs + outputs:
            lower = name.lower()
            if any(ind in lower for ind in ["struct", "array", "pointer", "queue", "buffer", "memory", "handle", "context", "instance", "reference"]):
                analysis["criteria"]["complex_data_types"] = True
                analysis["reasons"].append(f"Complex data type detected: {name}")
        if len(expressions.get("conditions", [])) > 2:
            analysis["criteria"]["normal_data_flow"] = False
            analysis["reasons"].append("Multiple conditions indicate complex control flow")
        if not inputs and not outputs:
            analysis["blocked"] = True
            analysis["reasons"].append("No input/output variables identified")
        if analysis["criteria"]["complex_data_types"]:
            analysis["recommended_method"] = "hybrid"
            analysis["criteria"]["requires_rvstest"] = True
            analysis["reasons"].append("Complex data types require Hybrid method with .rvstest")
        elif inputs or outputs:
            analysis["recommended_method"] = "direct"
            analysis["criteria"]["single_step_function"] = True
            analysis["criteria"]["at_most_one_init"] = True
            analysis["reasons"].append("Requirement appears suitable for Direct method")
        if component_name:
            uut_match = self._lookup_uut_entry(component_name)
            if uut_match:
                analysis["criteria"]["single_step_function"] = bool(uut_match.get("step fcn") or uut_match.get("stepFcn") or uut_match.get("step_fcn"))
                init_fcn = uut_match.get("initFcn") or uut_match.get("init fcn") or uut_match.get("init_fcn") or ""
                analysis["criteria"]["at_most_one_init"] = True if not init_fcn or isinstance(init_fcn, str) else False
                if str(uut_match.get("step fcn") or uut_match.get("stepFcn") or "").lower().find("rvstest") >= 0:
                    analysis["criteria"]["requires_rvstest"] = True
        return analysis

    def make_method_decision(self, result: Dict, component_name: str = None) -> Dict:
        repo_pattern = self.check_repo_pattern(component_name)
        uut_analysis = self.analyze_uut_for_method_decision(result, component_name)
        decision = {"selected_method": "unknown", "reason": "", "evidence": {"repo_pattern": repo_pattern, "uut_analysis": uut_analysis}, "rejected_modes": {}}
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
            decision["reason"] = f"Hybrid required by UUT analysis ({', '.join(uut_analysis['reasons'])})"
            decision["rejected_modes"]["direct"] = "Requirement requires procedure-vector behavior or complex data handling"
        elif uut_analysis["criteria"]["single_step_function"] and uut_analysis["criteria"]["at_most_one_init"] and uut_analysis["criteria"]["normal_data_flow"]:
            decision["selected_method"] = "direct"
            decision["reason"] = f"Direct method selected from UUT analysis ({', '.join(uut_analysis['reasons'])})"
            if repo_pattern["pattern"] == "hybrid":
                decision["rejected_modes"]["hybrid"] = "Repo examples exist but are advisory only"
        else:
            decision["selected_method"] = "blocked"
            decision["reason"] = "Blocked: insufficient evidence for a safe Direct or Hybrid choice"
        return decision
