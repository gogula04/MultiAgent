from __future__ import annotations

from typing import Dict


class RequirementReportMixin:
    def generate_step2_output(self, result: Dict) -> str:
        lines = ["## Inputs:"]
        inputs = result.get("inputs", [])
        inputs_header_found = result.get("source_file_findings", {}).get("inputs_found", [])
        inputs_citations = result.get("source_file_findings", {}).get("input_citations", {})
        if inputs:
            for i, inp in enumerate(inputs, 1):
                term_info = self.get_term_info(inp)
                if term_info:
                    inp_type = term_info.get("type", "unknown")
                    min_val = term_info.get("min") or ""
                    max_val = term_info.get("max") or ""
                    exact_value = term_info.get("value")
                    source = term_info.get("source", "data dictionary")
                    citation = term_info.get("citation") or term_info.get("source_path") or source
                    inp_type_str = f"function.csv({inp_type})" if source == "function.csv" else inp_type
                    exact_value_str = f" exact value: {exact_value}" if exact_value is not None else ""
                    lines.append(f"{i}. name: {inp} input type: {inp_type_str} min value: {min_val} max value: {max_val}{exact_value_str} found in: {source} citation: {citation}")
                elif inp in inputs_header_found:
                    citation = inputs_citations.get(inp, [])
                    citation_text = ", ".join(item.get("citation") or item.get("source_path") or "source file" for item in citation) if isinstance(citation, list) else ""
                    lines.append(f"{i}. name: {inp} input type: source file min value: max value: found in: source file citation: {citation_text}")
                else:
                    lines.append(f"{i}. name: {inp} input type: NOT FOUND min value: max value: found in: NOT FOUND")
        else:
            lines.append("No inputs identified.")
        lines += ["", "## Expressions:"]
        exprs = result.get("expressions", {})
        all_exprs = exprs.get("conditions", []) + exprs.get("comparisons", []) + exprs.get("calculations", [])
        lines += [f"{i}. {expr}" for i, expr in enumerate(all_exprs, 1)] or ["No expressions identified."]
        lines += ["", "## Outputs:"]
        outputs = result.get("outputs", [])
        outputs_header_found = result.get("source_file_findings", {}).get("outputs_found", [])
        outputs_citations = result.get("source_file_findings", {}).get("output_citations", {})
        if outputs:
            for i, out in enumerate(outputs, 1):
                term_info = self.get_term_info(out)
                if term_info:
                    out_type = term_info.get("type", "unknown")
                    source = term_info.get("source", "data dictionary")
                    citation = term_info.get("citation") or term_info.get("source_path") or source
                    out_type_str = f"function.csv({out_type})" if source == "function.csv" else out_type
                    exact_value = term_info.get("value")
                    exact_value_str = f" exact value: {exact_value}" if exact_value is not None else ""
                    lines.append(f"{i}. name: {out} type: {out_type_str}{exact_value_str} if expression 1 is true (TRUE), Default/ if False(FALSE) citation: {citation}")
                elif out in outputs_header_found:
                    citation = outputs_citations.get(out, [])
                    citation_text = ", ".join(item.get("citation") or item.get("source_path") or "source file" for item in citation) if isinstance(citation, list) else ""
                    lines.append(f"{i}. name: {out} type: source file if expression 1 is true (TRUE), Default/ if False(FALSE) citation: {citation_text}")
                else:
                    lines.append(f"{i}. name: {out} type: NOT FOUND if expression 1 is true (TRUE), Default/ if False(FALSE)")
        else:
            lines.append("No outputs identified.")
        types_and_ranges = result.get("types_and_ranges", [])
        if types_and_ranges:
            lines += ["", "## Types And Ranges"]
            for i, item in enumerate(types_and_ranges, 1):
                lines.append(
                    f"{i}. name: {item.get('name')} type: {item.get('type', item.get('type_hint', 'unknown'))} "
                    f"min: {item.get('min', '')} max: {item.get('max', '')} "
                    f"valid_values: {', '.join(map(str, item.get('valid_values', []))) if item.get('valid_values') else ''} "
                    f"invalid_values: {', '.join(map(str, item.get('invalid_values', []))) if item.get('invalid_values') else ''} "
                    f"source: {item.get('data_source', 'requirement text')}"
                )
        legacy_prompt_used = result.get("legacy_prompt_used", [])
        if legacy_prompt_used:
            lines += ["", "## Legacy Prompt Usage"]
            for i, item in enumerate(legacy_prompt_used, 1):
                lines.append(f"{i}. {item}")
        source_constants = result.get("source_constants", [])
        source_constraints = result.get("source_constraints", [])
        if source_constants:
            lines += ["", "## Source Constants"]
            for i, item in enumerate(source_constants, 1):
                lines.append(f"{i}. name: {item.get('name')} type: {item.get('type', 'unknown')} exact value: {item.get('value')} source: {item.get('source', 'source file')} citation: {item.get('citation') or item.get('source_path') or item.get('source', 'source file')}")
        if source_constraints:
            lines += ["", "## Source Constraints"]
            for i, item in enumerate(source_constraints, 1):
                lines.append(f"{i}. expression: {item.get('expression')} source: {item.get('source', 'source file')} line: {item.get('line', '')} citation: {item.get('citation') or item.get('source_path') or item.get('source', 'source file')}")
        return "\n".join(lines)
