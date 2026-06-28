from __future__ import annotations

from typing import Dict, List


class RequirementAssessMixin:
    def _generate_reasoning(self, classification: str, inputs: List[str], outputs: List[str], inputs_found: List[str], inputs_not_found: List[str], outputs_found: List[str], outputs_not_found: List[str], inputs_source_found: List[str], outputs_source_found: List[str], blockers: List[str]) -> str:
        reason = f"Classification: {classification}. "
        if inputs:
            reason += f"Found {len(inputs_found)}/{len(inputs)} input variables in data dictionary. "
        if outputs:
            reason += f"Found {len(outputs_found)}/{len(outputs)} output variables in data dictionary. "
        if inputs_source_found or outputs_source_found:
            reason += "Source evidence found for mapping. "
        if not inputs_found and not outputs_found:
            reason += "No variables found in data dictionary - requirement may need definition. "
        elif inputs_not_found or outputs_not_found:
            reason += "Some variables missing from data dictionary but tests may still be possible. "
        else:
            reason += "All variables found - requirement is testable. "
        if blockers:
            reason += f"Blockers: {', '.join(blockers)}. "
        return reason

    def _generate_proof_of_testability(self, inputs: List[str], outputs: List[str], inputs_dict_found: List[str], inputs_dict_not_found: List[str], outputs_dict_found: List[str], outputs_dict_not_found: List[str], inputs_source_found: List[str], outputs_source_found: List[str], blockers: List[str]) -> Dict:
        proof = {"testable": True, "analysis": {"inputs": {"defined_in_data_dictionary": inputs_dict_found, "not_in_data_dictionary": inputs_dict_not_found, "found_in_source": inputs_source_found, "count_defined": len(inputs_dict_found), "count_total": len(inputs)}, "outputs": {"defined_in_data_dictionary": outputs_dict_found, "not_in_data_dictionary": outputs_dict_not_found, "found_in_source": outputs_source_found, "count_defined": len(outputs_dict_found), "count_total": len(outputs)}}}
        total_defined = len(inputs_dict_found) + len(outputs_dict_found)
        total_needed = len(inputs) + len(outputs)
        if blockers:
            proof["testable"] = False
            proof["reason"] = "; ".join(blockers)
        elif total_needed == 0:
            proof["testable"] = False
            proof["reason"] = "No input or output variables identified - cannot write tests without defined variables"
        elif total_defined == 0:
            proof["testable"] = False
            proof["reason"] = "No variables found in data dictionary - requirement needs variable definitions"
        elif total_defined < total_needed:
            proof["reason"] = f"Partially defined: {total_defined}/{total_needed} variables found. Tests can be written for defined variables."
        else:
            proof["reason"] = f"All {total_needed} variables found - requirement is fully testable"
        return proof

    def evaluate(self, requirement_description: str, allow_source_reading: bool = False, poolside_client=None) -> Dict:
        self.load_data_dictionary_terms()
        self.load_uut_dictionary_terms()
        source_access_blocked = ""
        if allow_source_reading:
            try:
                self.load_source_terms()
            except PermissionError as exc:
                source_access_blocked = str(exc)
                self.source_terms = {}
                self.source_constants = []
                self.source_constraints = []
        else:
            self.source_terms = {}
            self.source_constants = []
            self.source_constraints = []
        classification = self.classify_requirement(requirement_description)
        notes: List[str] = []
        bold_terms = self.extract_bold_terms(requirement_description)
        types_and_ranges = self.extract_types_and_ranges(requirement_description)
        self.extracted_terms = {}
        for item in types_and_ranges:
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            self.extracted_terms[name.lower()] = {
                "name": name,
                "type": item.get("type") or item.get("type_hint") or "unknown",
                "source": item.get("data_source", "requirement text"),
                "min": item.get("min"),
                "max": item.get("max"),
                "valid_values": item.get("valid_values", []),
                "invalid_values": item.get("invalid_values", []),
                "default": item.get("default"),
                "role": item.get("role"),
                "section": item.get("section"),
                "constraints": item.get("constraints", []),
            }
        inputs, outputs = self.extract_variables(requirement_description)
        expressions = self.extract_expressions(requirement_description)

        legacy_prompt_used = []
        poolside_client = poolside_client or getattr(self, "poolside_client", None)
        if poolside_client is not None:
            legacy_payload = {
                "requirement_text": requirement_description,
                "classification": classification,
                "inputs": inputs,
                "outputs": outputs,
                "types_and_ranges": types_and_ranges,
                "expressions": expressions,
                "bold_terms": bold_terms,
                "data_dictionary_terms": list(self.data_dict_terms.keys())[:250],
                "uut_dictionary_terms": list(self.uut_dict_terms.keys())[:100],
                "data_dictionary_findings": {
                    "inputs_found": [],
                    "inputs_not_found": inputs[:],
                    "outputs_found": [],
                    "outputs_not_found": outputs[:],
                },
            }

            if self._needs_classification_fallback(classification, requirement_description):
                classification_hint = self._run_legacy_prompt(poolside_client, "legacy_classification", "classify_req.txt", legacy_payload)
                candidate_classification = str(classification_hint.get("type") or classification_hint.get("classification", "")).strip()
                if candidate_classification:
                    classification = candidate_classification
                    legacy_prompt_used.append("classify_req.txt")
                else:
                    notes.append("Legacy classification prompt returned no usable classification")

            need_io_prompt = not inputs or not outputs or not types_and_ranges
            if need_io_prompt:
                io_hint = self._run_legacy_prompt(poolside_client, "legacy_io_extraction", "io_vars_prompt_with_example.txt", legacy_payload)
                if io_hint:
                    inputs = self._merge_unique_strings(inputs, io_hint.get("inputs", []))
                    outputs = self._merge_unique_strings(outputs, io_hint.get("outputs", []))
                    types_and_ranges = self._merge_types_and_ranges(types_and_ranges, io_hint.get("types_and_ranges", []))
                    legacy_prompt_used.append("io_vars_prompt_with_example.txt")
                else:
                    notes.append("Legacy IO prompt returned no usable variables")

            need_expression_prompt = not any(expressions.get(key) for key in ("conditions", "comparisons", "calculations", "constants", "robustness_cases"))
            if need_expression_prompt:
                expr_hint = self._run_legacy_prompt(poolside_client, "legacy_expression_extraction", "expression_prompt.txt", legacy_payload)
                if expr_hint:
                    for key in ("conditions", "comparisons", "calculations", "constants", "robustness_cases"):
                        expressions[key] = self._merge_unique_strings(expressions.get(key, []), expr_hint.get(key, []))
                    legacy_prompt_used.append("expression_prompt.txt")
                else:
                    notes.append("Legacy expression prompt returned no usable expressions")

            signals = self._requirement_signals(requirement_description)
            needs_math_prompt = signals["math"] and not expressions.get("calculations")
            if needs_math_prompt:
                math_hint = self._run_legacy_prompt(poolside_client, "legacy_math_extraction", "math_extraction_prompt.txt", legacy_payload)
                if math_hint:
                    for key in ("calculations", "constants", "robustness_cases"):
                        expressions[key] = self._merge_unique_strings(expressions.get(key, []), math_hint.get(key, []))
                    types_and_ranges = self._merge_types_and_ranges(types_and_ranges, math_hint.get("types_and_ranges", []))
                    legacy_prompt_used.append("math_extraction_prompt.txt")
                else:
                    notes.append("Legacy math prompt returned no usable math details")

            needs_format_prompt = signals["format"] and not types_and_ranges
            if needs_format_prompt:
                format_hint = self._run_legacy_prompt(poolside_client, "legacy_format_extraction", "format_extration.txt", legacy_payload)
                if format_hint:
                    types_and_ranges = self._merge_types_and_ranges(types_and_ranges, format_hint.get("types_and_ranges", []))
                    for key in ("constants", "robustness_cases"):
                        expressions[key] = self._merge_unique_strings(expressions.get(key, []), format_hint.get(key, []))
                    legacy_prompt_used.append("format_extration.txt")
                else:
                    notes.append("Legacy format prompt returned no usable format details")

            needs_formatted_output_prompt = signals["format"] and (not inputs or not outputs)
            if needs_formatted_output_prompt:
                formatted_hint = self._run_legacy_prompt(poolside_client, "legacy_formatted_output_extraction", "formatted_output_exytraction_prompt.txt", legacy_payload)
                if formatted_hint:
                    inputs = self._merge_unique_strings(inputs, formatted_hint.get("inputs", []))
                    outputs = self._merge_unique_strings(outputs, formatted_hint.get("outputs", []))
                    types_and_ranges = self._merge_types_and_ranges(types_and_ranges, formatted_hint.get("types_and_ranges", []))
                    legacy_prompt_used.append("formatted_output_exytraction_prompt.txt")
                else:
                    notes.append("Legacy formatted-output prompt returned no usable variables")

        inferred_inputs = []
        inferred_outputs = []
        for item in types_and_ranges:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            role = str(item.get("role", "")).lower()
            lowered = name.lower()
            if role == "output" or any(k in lowered for k in ["return", "output", "result", "status", "success"]):
                inferred_outputs.append(name)
            else:
                inferred_inputs.append(name)
        inputs = self._merge_unique_strings(inputs, inferred_inputs)
        outputs = self._merge_unique_strings(outputs, inferred_outputs)
        inputs = self._normalize_string_list(inputs)
        outputs = self._normalize_string_list(outputs)
        bold_terms = self._normalize_string_list(bold_terms)
        types_and_ranges = self._normalize_types_and_ranges(types_and_ranges)
        expressions = self._normalize_expressions(expressions)
        legacy_prompt_used = self._normalize_string_list(legacy_prompt_used)

        extraction_contract = self._build_extraction_contract(
            requirement_description=requirement_description,
            classification=classification,
            inputs=inputs,
            outputs=outputs,
            bold_terms=bold_terms,
            types_and_ranges=types_and_ranges,
            expressions=expressions,
            legacy_prompt_used=legacy_prompt_used,
            notes=notes,
        )

        inputs_dict_found, inputs_dict_not_found = self.check_terms_in_dictionaries(inputs)
        outputs_dict_found, outputs_dict_not_found = self.check_terms_in_dictionaries(outputs)
        if allow_source_reading:
            inputs_source_found, inputs_source_not_found = self.check_terms_in_headers(inputs)
            outputs_source_found, outputs_source_not_found = self.check_terms_in_headers(outputs)
            inputs_source_citations = {term: self.get_header_evidence_for_term(term) for term in inputs_source_found}
            outputs_source_citations = {term: self.get_header_evidence_for_term(term) for term in outputs_source_found}
        else:
            inputs_source_found, inputs_source_not_found = [], inputs[:]
            outputs_source_found, outputs_source_not_found = [], outputs[:]
            inputs_source_citations = {}
            outputs_source_citations = {}
        inputs_dict_citations = {term: self.get_dictionary_evidence_for_term(term) for term in inputs_dict_found}
        outputs_dict_citations = {term: self.get_dictionary_evidence_for_term(term) for term in outputs_dict_found}
        uut_dictionary_evidence = self.get_uut_dictionary_evidence(inputs + outputs)
        constants = expressions.get("constants", [])
        robustness_cases = expressions.get("robustness_cases", [])
        missing_definitions = (inputs_dict_not_found + outputs_dict_not_found)[:]
        mapping_evidence = inputs_dict_found or outputs_dict_found or inputs_source_found or outputs_source_found
        can_write_tests = bool((inputs or outputs or constants) and mapping_evidence)
        if not inputs and not outputs:
            can_write_tests = False
            missing_definitions.append("No input or output variables identified")
        blockers = []
        if not (inputs or outputs or constants or expressions.get("conditions") or expressions.get("comparisons") or expressions.get("calculations")):
            blockers.append("No requirement structure identified")
        if not mapping_evidence:
            blockers.append("No data dictionary or source evidence to map the requirement" if allow_source_reading else "No data dictionary evidence to map the requirement before consulting source code")
        if source_access_blocked:
            blockers.append(source_access_blocked)
        if not can_write_tests:
            blockers.append("No executable verification path could be proven")
        return {
            "classification": classification,
            "bold_terms": bold_terms,
            "types_and_ranges": types_and_ranges,
            "legacy_prompt_used": legacy_prompt_used,
            "extraction_contract": extraction_contract,
            "testable": can_write_tests,
            "inputs": inputs,
            "outputs": outputs,
            "expressions": expressions,
            "constants": constants,
            "robustness_cases": robustness_cases,
            "source_constants": getattr(self, "source_constants", []),
            "source_constraints": getattr(self, "source_constraints", []),
            "source_access_blocked": source_access_blocked,
            "data_dictionary_findings": {
                "inputs_found": inputs_dict_found,
                "inputs_not_found": inputs_dict_not_found,
                "outputs_found": outputs_dict_found,
                "outputs_not_found": outputs_dict_not_found,
                "input_citations": inputs_dict_citations,
                "output_citations": outputs_dict_citations,
            },
            "source_file_findings": {
                "inputs_found": inputs_source_found,
                "inputs_not_found": inputs_source_not_found,
                "outputs_found": outputs_source_found,
                "outputs_not_found": outputs_source_not_found,
                "input_citations": inputs_source_citations,
                "output_citations": outputs_source_citations,
            },
            "uut_dictionary_findings": {
                "found": uut_dictionary_evidence["found"],
                "not_found": uut_dictionary_evidence["not_found"],
                "matches": uut_dictionary_evidence["matches"],
            },
            "testability_analysis": {
                "can_write_tests": can_write_tests,
                "reasoning": self._generate_reasoning(classification, inputs, outputs, inputs_dict_found, inputs_dict_not_found, outputs_dict_found, outputs_dict_not_found, inputs_source_found, outputs_source_found, blockers),
                "missing_definitions": missing_definitions,
                "blockers": blockers,
                "proof_of_testability": self._generate_proof_of_testability(inputs, outputs, inputs_dict_found, inputs_dict_not_found, outputs_dict_found, outputs_dict_not_found, inputs_source_found, outputs_source_found, blockers),
            },
        }
