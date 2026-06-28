"""File and report helpers for the multi-agent runtime."""

from __future__ import annotations

import csv
import re
import shutil
import subprocess
from xml.sax.saxutils import escape as xml_escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml_compat as yaml

from .core import normalize_term, render_json


class ArtifactSupport:
    def __init__(self, runtime: "VerificationCoordinator"):
        self.runtime = runtime

    def _format_rvstest_literal(self, value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return ""
        return str(value)

    def write_text(self, path: Path, content: str) -> None:
        if self.runtime.dry_run:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        self.runtime.generated_files.append(str(path))

    def append_csv_row(self, path: Path, header: List[str], row: List[Any]) -> None:
        if self.runtime.dry_run:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        exists = path.exists() and path.stat().st_size > 0
        with path.open("a", newline="") as f:
            writer = csv.writer(f)
            if not exists:
                writer.writerow(header)
            writer.writerow(row)
        self.runtime.generated_files.append(str(path))

    def append_yaml_entry(self, path: Path, entry: Dict[str, Any]) -> None:
        if self.runtime.dry_run:
            return
        existing: List[Dict[str, Any]] = []
        if path.exists():
            try:
                loaded = yaml.safe_load(path.read_text())
                if isinstance(loaded, list):
                    existing = loaded
                elif isinstance(loaded, dict):
                    existing = [loaded]
            except Exception:
                existing = []
        existing.append(entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(existing, sort_keys=False))
        self.runtime.generated_files.append(str(path))

    def append_data_dictionary(self, term: str, result: Dict[str, Any], element_type: str = "argument") -> None:
        component_name = result.get("component_name") or result.get("requirement_id") or "generated"
        snake = normalize_term(term)
        csv_path = self.runtime.procedure_data_dir / "data_dictionary.csv"
        yaml_path = self.runtime.procedure_data_dir / "data_dictionary.yaml"
        header = ["RequirementName", "VerificationIdentifier", "elementType", "stubReference", "baseDataType", "leafDataType"]
        term_info = self._term_info_for_result(result, term)
        base_type = self._normalize_type_name(term_info)
        aliases: List[str] = []
        extraction_contract = result.get("extraction_contract", {})
        if isinstance(extraction_contract, dict):
            alias_meta = extraction_contract.get("aliases", {}).get(term, {}) if isinstance(extraction_contract.get("aliases", {}), dict) else {}
            if isinstance(alias_meta, dict):
                aliases = list(alias_meta.get("variants", []) or [])
        if not aliases:
            aliases = [term, snake, snake.replace("_", " ")]
        aliases = list(dict.fromkeys([str(item).strip() for item in aliases if str(item).strip()]))
        csv_row = [term, snake, element_type, f"{component_name}[1]" if element_type == "argument" else component_name, base_type, base_type]
        yaml_entry = {"common": {element_type: [{"req_name": term, "ver_id": snake, "uut_name": f"{component_name}[1]" if element_type == "argument" else component_name, "base_data_type_name": base_type, "base_data_type_code": base_type, "aliases": aliases, "normalized_term": snake}]}}
        self.append_csv_row(csv_path, header, csv_row)
        self.append_yaml_entry(yaml_path, yaml_entry)

    def _term_info_for_result(self, result: Dict[str, Any], term: str) -> Dict[str, Any]:
        for item in result.get("types_and_ranges", []):
            if isinstance(item, dict) and str(item.get("name", "")).strip().lower() == term.lower():
                return item
        term_info = self.runtime.evaluator.get_term_info(term)
        if term_info:
            return term_info
        return {}

    def _normalize_type_name(self, term_info: Dict[str, Any]) -> str:
        type_text = str(
            term_info.get("base_data_type_name")
            or term_info.get("baseDataType")
            or term_info.get("leafDataType")
            or term_info.get("type")
            or term_info.get("type_hint")
            or "float"
        ).strip().lower()
        if not type_text:
            return "float"
        if any(token in type_text for token in ("bool", "boolean")):
            return "boolean"
        if any(token in type_text for token in ("enum", "enumeration")) or term_info.get("valid_values") or term_info.get("enum_values"):
            return "enum"
        if any(token in type_text for token in ("int", "integer", "uint", "long", "short")):
            return "int"
        if any(token in type_text for token in ("float", "double", "real")):
            return "float"
        if any(token in type_text for token in ("char", "string", "text")):
            return "string"
        if any(token in type_text for token in ("struct", "composite")):
            return "struct"
        if "array" in type_text:
            return "array"
        if "pointer" in type_text:
            return "pointer"
        return type_text

    def _needs_types_struct(self, result: Dict[str, Any]) -> bool:
        for item in result.get("types_and_ranges", []):
            if not isinstance(item, dict):
                continue
            type_text = str(item.get("type") or item.get("type_hint") or "").lower()
            name_text = str(item.get("name", "")).lower()
            if any(token in type_text for token in ("struct", "composite", "array", "pointer")):
                return True
            if any(marker in name_text for marker in ("->", ".", "[", "]")):
                return True
        return False

    def append_types_struct(self, result: Dict[str, Any]) -> Optional[Path]:
        if not self._needs_types_struct(result):
            return None
        csv_path = self.runtime.procedure_data_dir / "types_struct.csv"
        header = ["RequirementName", "TypeName", "TypeClass", "Detail", "Source"]
        requirement_name = result.get("component_name") or result.get("requirement_id") or "generated"
        created_path: Optional[Path] = None
        for item in result.get("types_and_ranges", []):
            if not isinstance(item, dict):
                continue
            type_class = self._normalize_type_name(item)
            if type_class not in {"struct", "composite", "array", "pointer"}:
                continue
            detail_parts = []
            for key in ("min", "max", "default"):
                value = item.get(key)
                if value not in {None, ""}:
                    detail_parts.append(f"{key}={value}")
            for key in ("valid_values", "invalid_values", "constraints"):
                value = item.get(key)
                if value:
                    if isinstance(value, list):
                        rendered = ", ".join(str(v) for v in value)
                    else:
                        rendered = str(value)
                    detail_parts.append(f"{key}={rendered}")
            detail = "; ".join(detail_parts) if detail_parts else "complex type inferred from requirement"
            row = [
                requirement_name,
                item.get("name", "unknown"),
                type_class,
                detail,
                item.get("data_source") or "requirement text",
            ]
            self.append_csv_row(csv_path, header, row)
            created_path = csv_path
        return created_path

    def build_rvstest(self, result: Dict[str, Any], req_id: str, component_name: str, branch_note: Optional[str] = None) -> Path:
        safe_component = normalize_term(component_name or req_id)
        rvstest_path = self.runtime.procedure_vectors_dir / "generated" / f"{safe_component}.rvstest"
        inputs = result.get("inputs", [])
        outputs = result.get("outputs", [])
        locals_: List[Tuple[str, str]] = []
        source_values: List[Tuple[str, Any]] = []
        for term in inputs + outputs:
            dd_name = f"dd_{normalize_term(term)}"
            term_info = self.runtime.evaluator.get_term_info(term)
            term_type = (term_info or {}).get("type", "UbtFloat")
            if not str(term_type).startswith("Ubt"):
                term_type = "UbtFloat"
            locals_.append((dd_name, term_type))
            source_value = None
            if hasattr(self.runtime.evaluator, "get_source_value_candidates"):
                candidates = self.runtime.evaluator.get_source_value_candidates(term)
                if candidates:
                    source_value = candidates[0]
            if source_value is None and term_info is not None and term_info.get("value") is not None:
                parser = getattr(self.runtime.evaluator, "_parse_source_evidence_literal", None)
                parsed_value = parser(term_info.get("value")) if callable(parser) else term_info.get("value")
                if parsed_value is not None:
                    source_value = parsed_value
            source_values.append((dd_name, source_value))
        if not locals_:
            locals_.append(("dd_placeholder", "UbtFloat"))
            source_values.append(("dd_placeholder", None))

        local_xml = []
        init_xml = []
        run_sets = []
        for idx, ((name, term_type), (_, source_value)) in enumerate(zip(locals_, source_values)):
            init_value = self._format_rvstest_literal(source_value)
            local_xml.append(f'<locals name="{name}" type="{term_type}"><initvals value="{init_value}" initcol_ref="//@tests.0/@localdecls/@initializations.0"/></locals>')
            init_xml.append(f'<valueactions xsi:type="testmodel:InitAction" uniqueName="//@tests.0/@localdecls/@locals.{idx}"><vectorVal_refs value="Init 1" vector_ref="//@tests.0/@actions/@vectors.0"/></valueactions>')
            run_sets.append(f'<setActions uniqueName="{name}" type="{term_type}"><vectorVal_refs value="{name}" vector_ref="//@tests.0/@actions/@vectors.0"/></setActions>')

        return_name = f"dd_{normalize_term(outputs[0])}" if outputs else "return_value"
        return_type = (self.runtime.evaluator.get_term_info(outputs[0]) or {}).get("type", "UbtFloat") if outputs else "UbtFloat"
        if not str(return_type).startswith("Ubt"):
            return_type = "UbtFloat"
        branch_note_xml = f'  <metadata key="BranchNote" value="{xml_escape(branch_note)}"/>\n' if branch_note else ""
        xml = f'''<?xml version="1.0" encoding="ASCII"?>
<testmodel xmi="2.0" xmlns="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://www.rapitasystems.com/testmodel" version="1.1">
  <tests name="Test 1 {component_name}">
    <localdecls>
      <initializations id="Init 1"/>
      {"".join(local_xml)}
    </localdecls>
    <actions>
      <vectors id="Vector 1"/>
      {"".join(init_xml)}
      <valueactions xsi:type="testmodel:RunAction" uniqueName="at function {component_name}">
        <vectorVal_refs value="" vector_ref="//@tests.0/@actions/@vectors.0"/>
        {"".join(run_sets)}
        <subActions xsi:type="testmodel:GlobalSetAction" uniqueName="{return_name}"><vectorVal_refs value="return" vector_ref="//@tests.0/@actions/@vectors.0"/></subActions>
      </valueactions>
    </actions>
    <metadata key="Traceability"/>
  </tests>
  <metadata key="Name" value="{component_name}"/>
  <metadata key="Project" value="rapitest"/>
  <metadata key="Author" value="LLT Agent"/>
{branch_note_xml}</testmodel>
'''
        self.write_text(rvstest_path, xml)
        return rvstest_path

    def run_pytest(self, test_file: Path, requirement_id: Optional[str] = None) -> Dict[str, Any]:
        if self.runtime.dry_run:
            return {"requirement_id": requirement_id or test_file.stem, "status": "dry_run", "command": f"pytest {test_file}", "exit_code": None, "stdout": "", "stderr": ""}
        try:
            completed = subprocess.run(["pytest", str(test_file), "-v", "--tb=short"], capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return {"requirement_id": requirement_id or test_file.stem, "status": "timeout", "command": f"pytest {test_file}", "exit_code": None, "stdout": "", "stderr": "Execution timed out"}
        except Exception as exc:
            return {"requirement_id": requirement_id or test_file.stem, "status": "error", "command": f"pytest {test_file}", "exit_code": None, "stdout": "", "stderr": str(exc)}
        status = "passed" if completed.returncode == 0 else "failed"
        return {"requirement_id": requirement_id or test_file.stem, "status": status, "command": f"pytest {test_file}", "exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}

    def render_report_markdown(self, report: Dict[str, Any]) -> str:
        method_decision = report.get("method_decision", {}) or {}
        proof_table = method_decision.get("proof_table", []) or []
        proof_status_line = report.get("rendered_summary") or f"Method proof: {'available' if proof_table else 'not generated'}"
        branch_note = report.get("branch_note") or method_decision.get("branch_note")
        alias_trace = report.get("alias_trace", {}) or {}
        extraction_aliases = report.get("extraction_aliases", {}) or {}
        reuse_candidates = report.get("reuse_candidates", []) or []
        lines = [
            "# LLT Verification Proof Report",
            "",
            f"- Requirement ID: {report.get('requirement_id')}",
            f"- Status: {report.get('status')}",
            f"- Method: {report.get('method_decision', {}).get('selected_method')}",
            f"- Branch note: {branch_note}" if branch_note else "- Branch note: not recorded",
            f"- {proof_status_line}",
            "",
            "## Summary",
            report.get("review", {}).get("summary", "Verification completed."),
            "",
            "## Alias Trace",
        ]
        if alias_trace:
            lines.extend(["| Term | Normalized | DD Name | Variants |", "| --- | --- | --- | --- |"])
            for term, meta in alias_trace.items():
                escaped_term = str(term).replace("|", "\\|")
                normalized = str(meta.get("normalized", "")).replace("|", "\\|")
                dd_name = str(meta.get("dd_name", "")).replace("|", "\\|")
                variants = ", ".join(str(v) for v in meta.get("variants", []) or [])
                variants = variants.replace("|", "\\|")
                lines.append(f"| {escaped_term} | {normalized} | {dd_name} | {variants} |")
        elif extraction_aliases:
            lines.extend(["| Term | Alias Metadata |", "| --- | --- |"])
            for term, meta in extraction_aliases.items():
                escaped_term = str(term).replace("|", "\\|")
                rendered = render_json(meta if isinstance(meta, dict) else {"value": meta})
                escaped_rendered = rendered.replace("|", "\\|")
                lines.append(f"| {escaped_term} | {escaped_rendered} |")
        else:
            lines.append("No alias trace was recorded.")
        lines.append("")
        lines.append("## Reuse Candidates")
        if reuse_candidates:
            lines.extend(["| Case ID | Requirement ID | Method | Score | Matched Terms |", "| --- | --- | --- | --- | --- |"])
            for candidate in reuse_candidates:
                if not isinstance(candidate, dict):
                    continue
                case_id = str(candidate.get("case_id", "")).replace("|", "\\|")
                requirement_id = str(candidate.get("requirement_id", "")).replace("|", "\\|")
                method = str(candidate.get("selected_method", "")).replace("|", "\\|")
                score = str(candidate.get("score", "")).replace("|", "\\|")
                matched_terms = ", ".join(str(term) for term in candidate.get("matched_terms", []) or []).replace("|", "\\|")
                lines.append(f"| {case_id} | {requirement_id} | {method} | {score} | {matched_terms} |")
        else:
            lines.append("No reuse candidates were found.")
        lines.extend([
            "",
            "## Method Proof",
        ])
        if proof_table:
            lines.extend(["| Branch | Verdict | Proof |", "| --- | --- | --- |"])
            for row in proof_table:
                branch = str(row.get("branch", "")).replace("|", "\\|")
                verdict = str(row.get("verdict", "")).replace("|", "\\|")
                proof = str(row.get("proof", "")).replace("|", "\\|")
                lines.append(f"| {branch} | {verdict} | {proof} |")
        else:
            lines.append("No method proof table was generated.")
        lines.append("")
        lines.append("## Files")
        for path in report.get("generated_files", []):
            lines.append(f"- {path}")
        lines.extend(["", "## Execution", render_json(report.get("execution_result", {})), "", "## Debug", render_json(report.get("debug_result", {})), "", "## Review", render_json(report.get("review", {}))])
        if report.get("learning_result") is not None:
            lines.extend(["", "## Learning", render_json(report.get("learning_result", {}))])
            method_template = report.get("learning_result", {}).get("method_template")
            if method_template:
                lines.extend(["", "## Learning Template", render_json(method_template)])
        return "\n".join(lines)
