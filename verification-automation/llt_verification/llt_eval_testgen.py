from __future__ import annotations

from typing import Dict, Optional


class RequirementTestGenMixin:
    def _source_value_for_term(self, term: str, result: Dict, fallback=None):
        candidates = self.get_source_value_candidates(term)
        if candidates:
            return candidates[0]
        source_constants = result.get("source_constants", [])
        for item in source_constants:
            if str(item.get("name", "")).lower() == term.lower():
                value = self._parse_source_evidence_literal(item.get("value"))
                if value is not None:
                    return value
        return fallback

    def _expected_literal_for_term(self, term: str, result: Dict, case_title: str = ""):
        source_value = self._source_value_for_term(term, result, None)
        if source_value is not None:
            return source_value
        term_info = self.get_term_info(term)
        if not term_info:
            return None
        term_type = str(term_info.get("type", "")).lower()
        has_explicit_value_evidence = any(
            term_info.get(key) is not None for key in ("default", "min", "max")
        ) or bool(term_info.get("enum_values") or term_info.get("valid_values") or term_info.get("choices") or term_info.get("options"))
        if not has_explicit_value_evidence:
            return None
        sample_values = self._sample_values_for_term(term, term_info)
        if any(token in term_type for token in {"enum", "enumeration"}):
            values = sample_values.get("valid_values") or []
            return values[0] if values else sample_values.get("nominal")
        if any(token in term_type for token in {"bool", "boolean"}):
            if term_info.get("default") is not None:
                return term_info.get("default")
            return sample_values.get("nominal")
        if any(token in term_type for token in {"float", "double", "real", "int", "integer", "uint", "long", "short"}):
            if term_info.get("default") is not None:
                return term_info.get("default")
            if term_info.get("min") is not None:
                return term_info.get("min")
            if term_info.get("max") is not None:
                return term_info.get("max")
            return sample_values.get("nominal")
        if any(token in term_type for token in {"string", "char", "text"}):
            if term_info.get("default") is not None:
                return term_info.get("default")
            return sample_values.get("nominal") if term_info.get("valid_values") or term_info.get("enum_values") else None
        if term_info.get("default") is not None:
            return term_info.get("default")
        return None

    def generate_test_case_file(self, result: Dict, req_id: str, description: str, component_name: Optional[str] = None, fixture_component: Optional[str] = None, branch_note: Optional[str] = None) -> str:
        inputs = result.get("inputs", [])
        outputs = result.get("outputs", [])
        effective_component = fixture_component or component_name or self.extract_component_name(description) or req_id
        lines = ["# Item ID: " + req_id]
        if branch_note:
            lines.extend([f"# Branch note: {branch_note}"])
        reuse_candidates = result.get("learning_reuse_candidates", []) or []
        if reuse_candidates:
            lines.append("# Learned reuse candidates:")
            for candidate in reuse_candidates[:3]:
                if not isinstance(candidate, dict):
                    continue
                lines.append(
                    f"# - {candidate.get('case_id')} ({candidate.get('selected_method')}, score={candidate.get('score')}, matched_terms={', '.join(candidate.get('matched_terms', []) or [])})"
                )
        lines.extend(["", "import pytest", "import pytest_smart as smart", "", "", "@pytest.fixture(autouse=True)", "def setUp(FW: smart.FW):", f'    FW.Set_Component("{effective_component}")', "    FW.Reset()", ""])
        tc_counter = 1
        emitted_cases = 0
        primary_input = None
        for inp in inputs:
            term_info = self.get_term_info(inp)
            if term_info and ((term_info.get("min") is not None and term_info.get("max") is not None) or term_info.get("enum_values") or term_info.get("valid_values")):
                primary_input = inp
                break
        if primary_input:
            term_info = self.get_term_info(primary_input)
            sample_values = self._sample_values_for_term(primary_input, term_info)
            source_nominal = self._source_value_for_term(primary_input, result)
            if source_nominal is not None:
                sample_values["nominal"] = source_nominal
                if isinstance(source_nominal, (int, float)):
                    sample_values.setdefault("minimum", source_nominal)
                    sample_values.setdefault("maximum", source_nominal)
            inp_type = self._map_to_rbtca_type(term_info.get("type", "unknown") if term_info else "unknown")
            def add_case(title: str, value, tc_id: int, extra_value=None):
                expected_literals = []
                for out in outputs:
                    expected = self._expected_literal_for_term(out, result, title)
                    if expected is None:
                        return False
                    expected_literals.append(expected)
                lines.extend(["# Purpose:", "# " + primary_input, "# " + title, f"def test_TC{tc_id:03d}(FW: smart.FW):", "    FW.Id(1)", f'    FW.Set("{primary_input}", {repr(value)})', "    FW.Run()"])
                for out, expected in zip(outputs, expected_literals):
                    lines.append(f'    FW.Verify("{out}", {repr(expected)})')
                if extra_value is not None:
                    lines.extend(["", "    FW.Id(2)", f'    FW.Set("{primary_input}", {repr(extra_value)})', "    FW.Run()"])
                    for out, expected in zip(outputs, expected_literals):
                        lines.append(f'    FW.Verify("{out}", {repr(expected)})')
                lines.append("")
                return True
            if inp_type == "Enumeration":
                valid_values = sample_values.get("valid_values") or [sample_values.get("nominal", "VALID")]
                invalid_value = sample_values.get("invalid", "__INVALID__")
                for value in valid_values:
                    if add_case(f"ENUM VALID {value}", value, tc_counter, invalid_value):
                        emitted_cases += 1
                        tc_counter += 1
                if not valid_values:
                    if add_case("ENUM NOMINAL", sample_values.get("nominal", "VALID"), tc_counter, invalid_value):
                        emitted_cases += 1
                        tc_counter += 1
                if emitted_cases == 0:
                    raise ValueError(f"Cannot generate evidence-backed test cases for {req_id}: output expectations are not proven")
                return "\n".join(lines)
            if inp_type == "Boolean":
                if add_case("BOOLEAN TRUE CASE", sample_values.get("true", True), tc_counter):
                    emitted_cases += 1
                    tc_counter += 1
                if add_case("BOOLEAN FALSE CASE", sample_values.get("false", False), tc_counter):
                    emitted_cases += 1
                    tc_counter += 1
            elif inp_type in {"Integer", "Float"}:
                if add_case("ROBUSTNESS - BELOW MINIMUM", sample_values.get("maximum", 1.0), tc_counter, sample_values.get("below_min", -1.0)):
                    emitted_cases += 1
                    tc_counter += 1
                if add_case("BOUNDARY EQUAL TO MINIMUM", sample_values.get("minimum", 0.0), tc_counter, sample_values.get("maximum", 1.0)):
                    emitted_cases += 1
                    tc_counter += 1
                if add_case("INDEPENDENCE TEST", sample_values.get("minimum", 0.0), tc_counter, sample_values.get("nominal", 1.0)):
                    emitted_cases += 1
                    tc_counter += 1
                if add_case("ROBUSTNESS - ZERO", sample_values.get("maximum", 1.0), tc_counter, sample_values.get("zero", 0.0)):
                    emitted_cases += 1
                    tc_counter += 1
                if add_case("ROBUSTNESS - ABOVE MAXIMUM", sample_values.get("minimum", 0.0), tc_counter, sample_values.get("above_max", 2.0)):
                    emitted_cases += 1
                    tc_counter += 1
            else:
                if add_case("NOMINAL CASE", sample_values.get("nominal", "VALID"), tc_counter):
                    emitted_cases += 1
                    tc_counter += 1
                if add_case("ALTERNATE CASE", sample_values.get("invalid", sample_values.get("nominal", "VALID")), tc_counter):
                    emitted_cases += 1
                    tc_counter += 1
        for cond in list(set(result.get("expressions", {}).get("conditions", []) + result.get("expressions", {}).get("comparisons", []))):
            expected_literals = []
            for out in outputs:
                expected = self._expected_literal_for_term(out, result, cond)
                if expected is None:
                    continue
                expected_literals.append(expected)
            if len(expected_literals) != len(outputs):
                continue
            lines += ["# Purpose:", "# Condition: " + cond, "# TRUE / BOUNDARY LESSER", f"def test_TC{tc_counter:03d}(FW: smart.FW):", "    FW.Id(1)", "    # Set inputs to make condition TRUE"]
            lines += [f'    FW.Set("{inp}", 1.0) # Set input for TRUE condition' for inp in inputs]
            lines.append("    FW.Run()")
            lines += [f'    FW.Verify("{out}", {repr(expected)})' for out, expected in zip(outputs, expected_literals)]
            lines.append(""); tc_counter += 1; emitted_cases += 1
            lines += ["# Purpose:", "# Condition: " + cond, "# FALSE / BOUNDARY EQUAL", f"def test_TC{tc_counter:03d}(FW: smart.FW):", "    FW.Id(1)", "    # Set inputs to make condition FALSE"]
            lines += [f'    FW.Set("{inp}", 0.0) # Set input for FALSE condition' for inp in inputs]
            lines.append("    FW.Run()")
            lines += [f'    FW.Verify("{out}", {repr(expected)})' for out, expected in zip(outputs, expected_literals)]
            lines.append(""); tc_counter += 1; emitted_cases += 1
            lines += ["# Purpose:", "# Condition: " + cond, "# TRUE / BOUNDARY GREATER", f"def test_TC{tc_counter:03d}(FW: smart.FW):", "    FW.Id(1)", "    # Set inputs at boundary greater"]
            lines += [f'    FW.Set("{inp}", 2.0) # Set input at boundary' for inp in inputs]
            lines.append("    FW.Run()")
            lines += [f'    FW.Verify("{out}", {repr(expected)})' for out, expected in zip(outputs, expected_literals)]
            lines.append(""); tc_counter += 1; emitted_cases += 1
        for calc in result.get("expressions", {}).get("calculations", []):
            expected_literals = []
            for out in outputs:
                expected = self._expected_literal_for_term(out, result, calc)
                if expected is None:
                    continue
                expected_literals.append(expected)
            if len(expected_literals) != len(outputs):
                continue
            lines += ["# Purpose:", "# " + calc, "# ROBUSTNESS: UNDERFLOW VALUE", f"def test_TC{tc_counter:03d}(FW: smart.FW):", "    FW.Id(1)", "    # Set inputs for underflow"]
            lines += [f'    FW.Set("{inp}", -1.0) # Underflow value' for inp in inputs]
            lines.append("    FW.Run()")
            lines += [f'    FW.Verify("{out}", {repr(expected)})' for out, expected in zip(outputs, expected_literals)]
            lines.append(""); tc_counter += 1; emitted_cases += 1
            lines += ["# Purpose:", "# " + calc, "# ROBUSTNESS: OVERFLOW VALUE", f"def test_TC{tc_counter:03d}(FW: smart.FW):", "    FW.Id(1)", "    # Set inputs for overflow"]
            lines += [f'    FW.Set("{inp}", 999999.0) # Overflow value' for inp in inputs]
            lines.append("    FW.Run()")
            lines += [f'    FW.Verify("{out}", {repr(expected)})' for out, expected in zip(outputs, expected_literals)]
            lines.append(""); tc_counter += 1; emitted_cases += 1
        if emitted_cases == 0:
            raise ValueError(f"Cannot generate evidence-backed test cases for {req_id}: output expectations are not proven")
        return "\n".join(lines)
