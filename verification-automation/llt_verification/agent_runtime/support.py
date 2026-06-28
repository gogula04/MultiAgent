"""File and report helpers for the peer-agent runtime."""

from __future__ import annotations

import csv
import re
import shutil
import subprocess
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
        csv_row = [term, snake, element_type, f"{component_name}[1]" if element_type == "argument" else component_name, "float", "float"]
        yaml_entry = {"common": {element_type: [{"req_name": term, "ver_id": snake, "uut_name": f"{component_name}[1]" if element_type == "argument" else component_name, "base_data_type_name": "float", "base_data_type_code": "float"}]}}
        self.append_csv_row(csv_path, header, csv_row)
        self.append_yaml_entry(yaml_path, yaml_entry)

    def build_rvstest(self, result: Dict[str, Any], req_id: str, component_name: str) -> Path:
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
</testmodel>
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
        lines = [
            "# LLT Verification Proof Report",
            "",
            f"- Requirement ID: {report.get('requirement_id')}",
            f"- Status: {report.get('status')}",
            f"- Method: {report.get('method_decision', {}).get('selected_method')}",
            "",
            "## Summary",
            report.get("review", {}).get("summary", "Verification completed."),
            "",
            "## Files",
        ]
        for path in report.get("generated_files", []):
            lines.append(f"- {path}")
        lines.extend(["", "## Execution", render_json(report.get("execution_result", {})), "", "## Review", render_json(report.get("review", {}))])
        return "\n".join(lines)
