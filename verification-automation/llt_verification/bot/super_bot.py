"""Super bot orchestrator for LLT verification.

This layer turns the existing verification helpers into a stage-based bot:
locate -> classify -> extract -> search -> decide -> generate -> run -> debug -> report.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from llt_verification import RequirementEvaluator
from scripts.workspace_utils import candidate_dirs, detect_workspace_root

from .providers import BotProvider, provider_from_env


class SuperBot:
    """High-level bot that executes the LLT verification workflow."""

    def __init__(
        self,
        workspace_root: Optional[str] = None,
        provider: Optional[BotProvider] = None,
        dry_run: bool = False,
        continue_on_failure: bool = False,
    ):
        self.workspace_root = detect_workspace_root(workspace_root)
        self.provider = provider or provider_from_env()
        self.dry_run = dry_run
        self.continue_on_failure = continue_on_failure

        self.evaluator = RequirementEvaluator(str(self.workspace_root))
        self.procedure_data_dir = (
            self.workspace_root / "verification" / "test-procedures" / "procedure-data"
        )
        self.test_cases_dir = self.workspace_root / "verification" / "test-cases" / "low_level"
        self.rbtca_dir = self.workspace_root / "records" / "rbtca" / "low_level"
        self.procedure_vectors_dir = (
            self.workspace_root / "verification" / "test-procedures" / "procedure-vectors"
        )
        self.source_dirs = candidate_dirs(
            self.workspace_root,
            [
                ("software", "source"),
                ("source",),
                ("src",),
            ],
            fallback_to_root=False,
        )

        self.generated_files: List[str] = []
        self.logs: List[str] = []
        self.stages: List[Dict[str, Any]] = []
        self.test_result: Dict[str, Any] = {}

    def _log(self, message: str, level: str = "INFO") -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = {"timestamp": timestamp, "level": level, "message": message}
        self.logs.append(f"[{timestamp}] [{level}] {message}")
        print(f"[{timestamp}] [{level}] {message}")

    def _record_stage(self, name: str, status: str, summary: str, data: Optional[Dict[str, Any]] = None) -> None:
        self.stages.append(
            {
                "stage": name,
                "status": status,
                "summary": summary,
                "data": data or {},
            }
        )

    def _safe_name(self, text: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")
        return safe or "generated"

    def _extract_requirement_id(self, prompt: str) -> Optional[str]:
        match = re.search(r"FAF-LLR-\d+", prompt)
        return match.group(0) if match else None

    def _relative_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.workspace_root))
        except Exception:
            return str(path)

    def _read_text(self, path: Path) -> Optional[str]:
        try:
            return path.read_text()
        except Exception:
            return None

    def _write_text(self, path: Path, content: str) -> None:
        if self.dry_run:
            self._log(f"DRY RUN: Would write {path}")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        self.generated_files.append(str(path))

    def _append_csv_row(self, path: Path, header: List[str], row: List[Any]) -> None:
        if self.dry_run:
            self._log(f"DRY RUN: Would append row to {path}")
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        has_header = path.exists()
        with path.open("a", newline="") as f:
            writer = csv.writer(f)
            if not has_header:
                writer.writerow(header)
            writer.writerow(row)

    def _append_yaml_entry(self, path: Path, entry: Dict[str, Any]) -> None:
        if self.dry_run:
            self._log(f"DRY RUN: Would append YAML entry to {path}")
            return

        path.parent.mkdir(parents=True, exist_ok=True)
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
        path.write_text(yaml.safe_dump(existing, sort_keys=False))

    def _append_data_dictionary(self, term: str, result: Dict[str, Any], element_type: str = "argument") -> None:
        component_name = result.get("component_name") or result.get("requirement_id") or "generated"
        snake = self._safe_name(term).lower()
        csv_path = self.procedure_data_dir / "data_dictionary.csv"
        yaml_path = self.procedure_data_dir / "data_dictionary.yaml"
        header = [
            "RequirementName",
            "VerificationIdentifier",
            "elementType",
            "stubReference",
            "baseDataType",
            "leafDataType",
        ]
        csv_row = [
            term,
            snake,
            element_type,
            f"{component_name}[1]" if element_type == "argument" else component_name,
            "float",
            "float",
        ]
        yaml_entry = {
            "common": {
                element_type: [
                    {
                        "req_name": term,
                        "ver_id": snake,
                        "uut_name": f"{component_name}[1]" if element_type == "argument" else component_name,
                        "base_data_type_name": "float",
                        "base_data_type_code": "float",
                    }
                ]
            }
        }
        self._append_csv_row(csv_path, header, csv_row)
        self._append_yaml_entry(yaml_path, yaml_entry)
        self._log(f"Added {term} to data dictionary")

    def _ensure_uut_dictionary_entry(self, component_name: str) -> None:
        csv_path = self.procedure_data_dir / "uut_dictionary.csv"
        yaml_path = self.procedure_data_dir / "uut_dictionary.yaml"
        if self.dry_run:
            self._log(f"DRY RUN: Would update UUT dictionary for {component_name}")
            return

        existing = csv_path.read_text(errors="ignore") if csv_path.exists() else ""
        if component_name in existing:
            self._log(f"UUT dictionary already contains {component_name}")
            return

        header = [
            "uut name",
            "rate",
            "initFcn",
            "return",
            "step fcn",
            "return_stepfn",
            "mockFcns",
            "preconditions comma sep",
        ]
        row = [component_name, "0.005", "", "void", component_name, "void", "", ""]
        yaml_entry = {
            "uut_name": component_name,
            "rate": "0.005",
            "init_fcn": "",
            "step_fcn": component_name,
            "step_fcn_return": "void",
            "mock_fcns": [],
            "preconditions": [],
        }
        self._append_csv_row(csv_path, header, row)
        self._append_yaml_entry(yaml_path, yaml_entry)
        self._log(f"Added UUT entry for {component_name}")

    def _build_rvstest(self, result: Dict[str, Any], req_id: str, component_name: str) -> Path:
        safe_component = self._safe_name(component_name or req_id)
        rvstest_path = self.procedure_vectors_dir / "generated" / f"{safe_component}.rvstest"
        inputs = result.get("inputs", [])
        outputs = result.get("outputs", [])
        locals_ = []
        for term in inputs + outputs:
            safe_term = self._safe_name(term)
            dd_name = f"dd_{safe_term}"
            term_info = self.evaluator.get_term_info(term)
            term_type = (term_info or {}).get("type", "UbtFloat")
            if not str(term_type).startswith("Ubt"):
                term_type = "UbtFloat"
            locals_.append((dd_name, term_type))

        if not locals_:
            locals_.append(("dd_placeholder", "UbtFloat"))

        local_xml = []
        init_xml = []
        for idx, (name, term_type) in enumerate(locals_):
            local_xml.append(
                f'<locals name="{name}" type="{term_type}"><initvals value="" initcol_ref="//@tests.0/@localdecls/@initializations.0"/></locals>'
            )
            init_xml.append(
                f'<valueactions xsi:type="testmodel:InitAction" uniqueName="//@tests.0/@localdecls/@locals.{idx}"><vectorVal_refs value="Init 1" vector_ref="//@tests.0/@actions/@vectors.0"/></valueactions>'
            )

        run_sets = []
        for idx, (name, term_type) in enumerate(locals_):
            run_sets.append(
                f'<setActions uniqueName="{name}" type="{term_type}"><vectorVal_refs value="{name}" vector_ref="//@tests.0/@actions/@vectors.0"/></setActions>'
            )

        return_name = f"dd_{self._safe_name(outputs[0])}" if outputs else "return_value"
        return_type = (self.evaluator.get_term_info(outputs[0]) or {}).get("type", "UbtFloat") if outputs else "UbtFloat"
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
  <metadata key="Author" value="LLT Super Bot"/>
</testmodel>
'''
        self._write_text(rvstest_path, xml)
        return rvstest_path

    def _run_tests(self, test_file: Path) -> Dict[str, Any]:
        if self.dry_run:
            self._log(f"DRY RUN: Would run pytest {test_file}")
            return {"status": "dry_run", "command": f"pytest {test_file}"}

        self._log(f"Running tests: pytest {test_file}")
        try:
            result = subprocess.run(
                ["pytest", str(test_file), "-v", "--tb=short"],
                capture_output=True,
                text=True,
                timeout=90,
            )
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "command": f"pytest {test_file}", "exit_code": None}
        except Exception as exc:
            return {"status": "error", "command": f"pytest {test_file}", "error": str(exc)}

        if result.returncode == 0:
            return {
                "status": "passed",
                "command": f"pytest {test_file}",
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        return {
            "status": "failed",
            "command": f"pytest {test_file}",
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def _debug_and_fix(self, test_file: Path, result: Dict[str, Any], req_id: str) -> Dict[str, Any]:
        content = self._read_text(test_file)
        if not content:
            return self._run_tests(test_file)

        placeholder_pattern = r'FW\.Verify\("([^"]+)",\s*0(?:\.0)?\)\s*# Placeholder - adjust based on requirement'
        todo_pattern = r'# TODO: FW\.Verify\("([^"]+)", expected_value\)'
        terms = re.findall(placeholder_pattern, content) + re.findall(todo_pattern, content)
        if not terms:
            return self._run_tests(test_file)

        for term in set(terms):
            term_info = self.evaluator.get_term_info(term)
            replacement = "False" if "bool" in str((term_info or {}).get("type", "")).lower() else "0.0"
            content = content.replace(
                f'FW.Verify("{term}", 0.0) # Placeholder - adjust based on requirement',
                f'FW.Verify("{term}", {replacement}) # Placeholder - adjust based on requirement',
            )
            content = content.replace(
                f'# TODO: FW.Verify("{term}", expected_value)',
                f'FW.Verify("{term}", {replacement}) # Placeholder - adjust based on requirement',
            )

        self._write_text(test_file, content)
        return self._run_tests(test_file)

    def _generate_report(
        self,
        requirement_id: str,
        description: str,
        result: Dict[str, Any],
        method_decision: Dict[str, Any],
        rbtca_file: Optional[Path],
        test_file: Optional[Path],
        rvstest_file: Optional[Path],
        test_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        report = {
            "status": "completed",
            "requirement_id": requirement_id,
            "description": description,
            "classification": result.get("classification"),
            "bold_terms": result.get("bold_terms", []),
            "inputs": result.get("inputs", []),
            "outputs": result.get("outputs", []),
            "expressions": result.get("expressions", {}),
            "data_dictionary_findings": result.get("data_dictionary_findings", {}),
            "source_file_findings": result.get("source_file_findings", {}),
            "uut_dictionary_findings": result.get("uut_dictionary_findings", {}),
            "method_decision": method_decision,
            "generated_files": self.generated_files,
            "pipeline_stages": self.stages,
            "test_result": test_result,
            "recommendations": [],
        }

        if rbtca_file:
            report["rbtca_file"] = str(rbtca_file)
        if test_file:
            report["test_file"] = str(test_file)
        if rvstest_file:
            report["rvstest_file"] = str(rvstest_file)

        if test_result.get("status") == "passed":
            report["status"] = "passed"
        elif test_result.get("status") in {"failed", "timeout", "error"}:
            report["status"] = "needs_debugging"
        elif method_decision.get("selected_method") == "blocked":
            report["status"] = "blocked"
        elif test_result.get("status") == "dry_run":
            report["status"] = "dry_run_complete"

        missing = (
            result.get("data_dictionary_findings", {}).get("inputs_not_found", [])
            + result.get("data_dictionary_findings", {}).get("outputs_not_found", [])
        )
        if missing:
            report["recommendations"].append(
                f"Add missing variables to data dictionary: {', '.join(missing[:3])}"
            )
        if method_decision.get("selected_method") == "hybrid" and not rvstest_file:
            report["recommendations"].append("Generate .rvstest for the Hybrid path")
        if test_result.get("status") == "failed":
            report["recommendations"].append("Inspect failure logs and update expected values or mappings")
        if not report["recommendations"]:
            report["recommendations"].append("Verification complete - no further action needed")

        return report

    def run(self, requirement: str) -> Dict[str, Any]:
        self.generated_files = []
        self.logs = []
        self.stages = []
        self.test_result = {}

        self._log(f"Starting super bot verification for: {requirement}")
        self._record_stage("trigger", "started", "Received verification request", {"input": requirement})

        req_id_match = self._extract_requirement_id(requirement)
        req_id = req_id_match or f"custom-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        description = requirement
        requirement_file = None

        if req_id_match:
            description, requirement_path = self.evaluator.find_requirement_by_id(req_id_match)
            if not description:
                self._record_stage("locate_requirement", "blocked", "Requirement not found", {"requirement_id": req_id_match})
                return {
                    "status": "failed",
                    "reason": "Requirement not found",
                    "requirement_id": req_id_match,
                    "pipeline_stages": self.stages,
                }
            requirement_file = str(requirement_path)
            self._record_stage(
                "locate_requirement",
                "completed",
                "Requirement located",
                {"requirement_file": requirement_file},
            )
        else:
            self._record_stage("locate_requirement", "completed", "Requirement text provided directly")

        provider_plan = self.provider.complete(
            "plan",
            {
                "requirement_id": req_id,
                "requirement_text": description,
            },
        )
        self._record_stage("provider_plan", "completed", "Optional provider planning step", provider_plan)

        base_result = self.evaluator.evaluate(description, allow_source_reading=False)
        base_result["requirement_id"] = req_id
        base_result["requirement_file"] = requirement_file
        base_result["bold_terms"] = base_result.get("bold_terms", [])
        base_result["component_name"] = self.evaluator.extract_component_name(description)
        self._record_stage(
            "classify_extract",
            "completed",
            "Requirement classified and extracted",
            {
                "classification": base_result.get("classification"),
                "inputs": base_result.get("inputs", []),
                "outputs": base_result.get("outputs", []),
                "bold_terms": base_result.get("bold_terms", []),
                "testable": base_result.get("testable", False),
            },
        )

        if not base_result.get("testable", False):
            fallback_result = self.evaluator.evaluate(description, allow_source_reading=True)
            fallback_result["requirement_id"] = req_id
            fallback_result["requirement_file"] = requirement_file
            fallback_result["component_name"] = base_result.get("component_name")
            fallback_result["bold_terms"] = fallback_result.get("bold_terms", base_result.get("bold_terms", []))
            base_result = fallback_result
            self._record_stage(
                "implementation_fallback",
                "completed",
                "Implementation/source fallback consulted",
                {"testable": base_result.get("testable", False)},
            )

        search_terms = list(dict.fromkeys(base_result.get("bold_terms", []) + base_result.get("inputs", []) + base_result.get("outputs", [])))
        base_result["search_terms"] = search_terms
        self._record_stage(
            "dictionary_search",
            "completed",
            "Collected terms for repository search",
            {"search_terms": search_terms},
        )

        method_decision = self.evaluator.make_method_decision(base_result, base_result.get("component_name"))
        base_result["method_decision"] = method_decision
        self._record_stage(
            "method_decision",
            "completed",
            "Direct / Hybrid / Blocked decision made",
            method_decision,
        )

        if method_decision.get("selected_method") == "blocked":
            report = self._generate_report(
                req_id,
                description,
                base_result,
                method_decision,
                None,
                None,
                None,
                {"status": "blocked", "reason": method_decision.get("reason", "Blocked")},
            )
            self._record_stage("blocked", "completed", method_decision.get("reason", "Blocked"))
            return report

        component_name = base_result.get("component_name") or req_id
        rbtca_content, _ = self.evaluator.generate_rbtca_yaml(base_result, req_id)
        rbtca_file = self.rbtca_dir / f"{req_id}.yaml"
        self._write_text(rbtca_file, yaml.safe_dump(rbtca_content, sort_keys=False))
        self._record_stage(
            "rbtca_generation",
            "completed",
            "Generated RBTCA YAML",
            {"rbtca_file": str(rbtca_file)},
        )

        fixture_component = component_name
        rvstest_file = None
        if method_decision.get("selected_method") == "hybrid":
            rvstest_file = self._build_rvstest(base_result, req_id, component_name)
            fixture_component = self._relative_path(rvstest_file)
            self._record_stage(
                "hybrid_artifacts",
                "completed",
                "Generated Hybrid .rvstest procedure vector",
                {"rvstest_file": str(rvstest_file), "fixture_component": fixture_component},
            )
        else:
            self._ensure_uut_dictionary_entry(component_name)
            self._record_stage(
                "direct_artifacts",
                "completed",
                "Updated Direct dictionaries",
                {"uut_component": component_name},
            )

        test_content = self.evaluator.generate_test_case_file(
            base_result,
            req_id,
            description,
            component_name,
            fixture_component=fixture_component,
        )
        test_file = self.test_cases_dir / f"test_{req_id}.py"
        self._write_text(test_file, test_content)
        self._record_stage(
            "python_generation",
            "completed",
            "Generated Python pytest_smart testcase",
            {"test_file": str(test_file)},
        )

        if "Placeholder" in test_content or "# TODO" in test_content:
            self._log("Generated test contains placeholder values; debug loop may be needed", "WARNING")

        if method_decision.get("selected_method") == "direct":
            missing_inputs = base_result.get("data_dictionary_findings", {}).get("inputs_not_found", [])
            missing_outputs = base_result.get("data_dictionary_findings", {}).get("outputs_not_found", [])
            for term in missing_inputs:
                self._append_data_dictionary(term, base_result, "argument")
            for term in missing_outputs:
                self._append_data_dictionary(term, base_result, "return")
        else:
            missing_inputs = base_result.get("data_dictionary_findings", {}).get("inputs_not_found", [])
            missing_outputs = base_result.get("data_dictionary_findings", {}).get("outputs_not_found", [])
            for term in missing_inputs:
                self._append_data_dictionary(term, base_result, "argument")
            for term in missing_outputs:
                self._append_data_dictionary(term, base_result, "return")

        self._record_stage(
            "artifact_sync",
            "completed",
            "Synchronized dictionaries and supporting artifacts",
            {
                "missing_inputs": missing_inputs,
                "missing_outputs": missing_outputs,
            },
        )

        test_result = self._run_tests(test_file)
        self.test_result = test_result
        self._record_stage(
            "test_run",
            test_result.get("status", "unknown"),
            "Executed generated tests",
            test_result,
        )

        if test_result.get("status") == "failed" and self.continue_on_failure:
            self._record_stage("debug", "started", "Debugging failed test run")
            test_result = self._debug_and_fix(test_file, base_result, req_id)
            self.test_result = test_result
            self._record_stage(
                "debug",
                test_result.get("status", "unknown"),
                "Debug loop finished",
                test_result,
            )

        report = self._generate_report(
            req_id,
            description,
            base_result,
            method_decision,
            rbtca_file,
            test_file,
            rvstest_file,
            test_result,
        )
        self._record_stage("report", "completed", "Generated proof report", report)

        if provider_plan:
            self._record_stage("provider_report", "completed", "Optional provider reporting step", provider_plan)

        report["pipeline_stages"] = self.stages
        report["generated_files"] = self.generated_files

        return report


def run_super_bot(requirement: str, workspace_root: Optional[str] = None, dry_run: bool = False, continue_on_failure: bool = False) -> Dict[str, Any]:
    """Convenience entrypoint for the super bot."""
    bot = SuperBot(
        workspace_root=workspace_root,
        dry_run=dry_run,
        continue_on_failure=continue_on_failure,
    )
    return bot.run(requirement)
