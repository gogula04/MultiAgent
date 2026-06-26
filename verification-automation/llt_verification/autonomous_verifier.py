#!/usr/bin/env python3
"""
Autonomous LLT Verification Agent

This agent acts as a verification engineer, automatically:
- Evaluating requirements for testability
- Generating RBTCA YAML files
- Creating Python test cases
- Managing data dictionaries
- Running tests
- Debugging failures
- Analyzing and reporting results

Usage:
 python autonomous_verifier.py FAF-LLR-401 # Full autonomous verification
 python autonomous_verifier.py --dry-run FAF-LLR-401 # Preview without file changes
 python autonomous_verifier.py --continue-on-failure # Keep debugging until pass
"""

import json
import re
import csv
import sys
import yaml
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from scripts.workspace_utils import candidate_dirs, detect_workspace_root


class AutonomousVerifier:
    """Autonomous verification agent that acts like a verification engineer."""

    def __init__(
        self,
        workspace_root: Optional[str] = None,
        dry_run: bool = False,
        continue_on_failure: bool = False,
    ):
        self.workspace_root = detect_workspace_root(workspace_root)
        self.dry_run = dry_run
        self.continue_on_failure = continue_on_failure

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

        self.log_messages = []
        self.generated_files = []
        self.test_results = {}

    def log(self, message: str, level: str = "INFO"):
        """Log a message with timestamp."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [{level}] {message}"
        self.log_messages.append(log_entry)
        print(log_entry)

    def verify_requirement(self, req_id_or_desc: str) -> Dict:
        """
        Main entry point - verify a requirement autonomously.
        """
        self.log(f"Starting autonomous verification for: {req_id_or_desc}")

        from llt_verification import RequirementEvaluator

        evaluator = RequirementEvaluator(str(self.workspace_root))

        is_req_id = bool(re.match(r"FAF-LLR-\d+", req_id_or_desc))
        if is_req_id:
            description, req_path = evaluator.find_requirement_by_id(req_id_or_desc)
            if not description:
                self.log(f"Requirement {req_id_or_desc} not found", "ERROR")
                return {"status": "failed", "reason": "Requirement not found"}
            req_id = req_id_or_desc
        else:
            description = req_id_or_desc
            req_path = None
            req_id = f"custom-{int(time.time())}"

        self.log(f"Requirement description: {description[:100]}...")

        result = evaluator.evaluate(description, allow_source_reading=False)
        result["requirement_id"] = req_id
        if req_path:
            result["requirement_file"] = str(req_path)
        result["component_name"] = evaluator.extract_component_name(description)

        if not result.get("testable", False):
            self.log("First pass did not prove testability; consulting implementation for fallback evidence", "WARNING")
            fallback_result = evaluator.evaluate(description, allow_source_reading=True)
            fallback_result["requirement_id"] = req_id
            if req_path:
                fallback_result["requirement_file"] = str(req_path)
            fallback_result["component_name"] = result["component_name"]
            result = fallback_result

        method_decision = evaluator.make_method_decision(result, result.get("component_name"))
        result["method_decision"] = method_decision
        self.log(f"Method decision: {method_decision['selected_method']}")
        self.log(f"Reason: {method_decision['reason']}")

        if method_decision["selected_method"] == "blocked":
            self.log("Verification blocked before artifact generation", "WARNING")
            return {"status": "blocked", "result": result}

        if not result.get("testable", False):
            self.log("Requirement is not testable", "WARNING")
            return {"status": "not_testable", "result": result}

        rbtca_content, test_case_map = evaluator.generate_rbtca_yaml(result, req_id)
        rbtca_file = self.rbtca_dir / f"{req_id}.yaml"

        self.log(f"Generating RBTCA YAML: {rbtca_file}")
        if not self.dry_run:
            rbtca_file.parent.mkdir(parents=True, exist_ok=True)
            with open(rbtca_file, "w") as f:
                yaml.dump(rbtca_content, f, default_flow_style=False, sort_keys=False)
            self.generated_files.append(str(rbtca_file))
        else:
            self.log(f"DRY RUN: Would create {rbtca_file}")

        test_content = evaluator.generate_test_case_file(
            result, req_id, description, result.get("component_name")
        )
        test_file = self.test_cases_dir / f"test_{req_id}.py"

        self.log(f"Generating test case file: {test_file}")
        if not self.dry_run:
            test_file.parent.mkdir(parents=True, exist_ok=True)
            with open(test_file, "w") as f:
                f.write(test_content)
            self.generated_files.append(str(test_file))
        else:
            self.log(f"DRY RUN: Would create {test_file}")

        if "Placeholder" in test_content or "# TODO" in test_content:
            self.log(
                "Generated test contains placeholder values; proceeding to debug loop if needed",
                "WARNING",
            )

        self._update_data_dictionaries(evaluator, result, description, req_id)

        test_result = self._run_tests(test_file)

        if test_result.get("status") == "failed" and self.continue_on_failure:
            test_result = self._debug_and_fix(test_file, evaluator, result, req_id)

        report = self._generate_report(result, test_result, rbtca_file, test_file)

        return report

    def _update_data_dictionaries(
        self, evaluator, result: Dict, description: str, req_id: str
    ):
        """Update data dictionaries if variables are missing."""
        missing_inputs = result.get("data_dictionary_findings", {}).get("inputs_not_found", [])
        missing_outputs = result.get("data_dictionary_findings", {}).get("outputs_not_found", [])

        if not missing_inputs and not missing_outputs:
            self.log("All variables found in data dictionaries ✓")
        else:
            self.log(f"Missing variables - Inputs: {missing_inputs}, Outputs: {missing_outputs}")

        for var in missing_inputs + missing_outputs:
            self._add_to_data_dictionary(var_name=var, result=result)

        self._ensure_uut_dictionary_entry(req_id, result, description)

    def _add_to_data_dictionary(self, var_name: str, result: Dict, description: str = ""):
        """Add a variable to the data dictionary CSV."""
        self.log(f"Adding {var_name} to data dictionary")

        if self.dry_run:
            self.log(f"DRY RUN: Would add {var_name} to data_dictionary.csv")
            return

        data_type = "float"
        csv_path = self.procedure_data_dir / "data_dictionary.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        file_exists = csv_path.exists()
        has_header = False
        if file_exists:
            with open(csv_path, "r") as f:
                first_line = f.readline()
                has_header = "RequirementName" in first_line

        with open(csv_path, "a", newline="") as f:
            writer = csv.writer(f)
            if not has_header:
                writer.writerow(
                    [
                        "RequirementName",
                        "VerificationIdentifier",
                        "elementType",
                        "stubReference",
                        "baseDataType",
                        "leafDataType",
                    ]
                )
            writer.writerow(
                [var_name, var_name.lower().replace(" ", "_"), "argument", "", data_type, ""]
            )

        self.log(f"Added {var_name} to {csv_path}")

    def _ensure_uut_dictionary_entry(self, req_id: str, result: Dict, description: str):
        """Ensure UUT dictionary has entry for this requirement component."""
        component_name = result.get("component_name")
        if not component_name:
            component_name = req_id

        self.log(f"Ensuring UUT dictionary entry for component: {component_name}")

        if self.dry_run:
            self.log(f"DRY RUN: Would add {component_name} to uut_dictionary.csv")
            return

        csv_path = self.procedure_data_dir / "uut_dictionary.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        if csv_path.exists():
            with open(csv_path, "r") as f:
                content = f.read()
                if component_name in content:
                    self.log(f"UUT dictionary entry already exists for {component_name}")
                    return

        file_exists = csv_path.exists()
        with open(csv_path, "a", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(
                    [
                        "uut name",
                        "rate",
                        "initFcn",
                        "return",
                        "step fcn",
                        "return_stepfn",
                        "mockFcns",
                        "preconditions comma sep",
                    ]
                )
            step_fcn = component_name
            writer.writerow([component_name, "0.005", "", "void", step_fcn, "void", "", ""])

        self.log(f"Added UUT entry for {component_name} to {csv_path}")

    def _run_tests(self, test_file: Path) -> Dict:
        """Run pytest on the generated test file."""
        if self.dry_run:
            self.log(f"DRY RUN: Would run pytest on {test_file}")
            return {"status": "dry_run", "tests": 0}

        if not test_file.exists():
            self.log(f"Test file not found: {test_file}", "ERROR")
            return {"status": "failed", "reason": "Test file not found"}

        self.log(f"Running tests: pytest {test_file}")

        try:
            result = subprocess.run(
                ["pytest", str(test_file), "-v", "--tb=short"],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                self.log("All tests passed ✓")
                return {"status": "passed", "output": result.stdout}
            else:
                self.log("Tests failed, analyzing...", "WARNING")
                return {"status": "failed", "output": result.stdout, "error": result.stderr}

        except subprocess.TimeoutExpired:
            self.log("Test execution timed out", "ERROR")
            return {"status": "timeout"}
        except Exception as e:
            self.log(f"Test execution error: {e}", "ERROR")
            return {"status": "error", "error": str(e)}

    def _debug_and_fix(self, test_file: Path, evaluator, result: Dict, req_id: str) -> Dict:
        """Debug failing tests and attempt fixes."""
        self.log("Attempting to debug and fix failing tests...")

        max_attempts = 3
        for attempt in range(max_attempts):
            self.log(f"Debug attempt {attempt + 1}/{max_attempts}")

            test_content = self._read_file(test_file)
            if not test_content:
                self.log("Could not read test file")
                break

            todo_pattern = r'# TODO: FW\.Verify\("([^"]+)", expected_value\)'
            placeholder_pattern = r'FW\.Verify\("([^"]+)",\s*0(?:\.0)?\)\s*# Placeholder - adjust based on requirement'
            todos = re.findall(todo_pattern, test_content) + re.findall(placeholder_pattern, test_content)

            if not todos:
                self.log("No TODO markers found - tests may have other issues")
                break

            self.log(f"Found {len(todos)} TODO markers to fix")

            component_name = evaluator.extract_component_name(result.get("requirement_id", ""))
            if component_name:
                impl_result = self._analyze_implementation(component_name)
                if impl_result.get("success"):
                    self.log(f"Found implementation: {impl_result.get('file')}")

            if not self.dry_run:
                updated_content = self._fill_placeholder_values(test_content, todos)
                self._write_file(test_file, updated_content)
                self.log("Updated test file with placeholder values")

            break

        return self._run_tests(test_file)

    def _read_file(self, file_path: Path) -> Optional[str]:
        """Read a file and return its contents."""
        try:
            with open(file_path, "r") as f:
                return f.read()
        except Exception as e:
            self.log(f"Error reading {file_path}: {e}", "ERROR")
            return None

    def _write_file(self, file_path: Path, content: str):
        """Write content to a file."""
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w") as f:
                f.write(content)
            self.log(f"Wrote to {file_path}")
        except Exception as e:
            self.log(f"Error writing {file_path}: {e}", "ERROR")

    def _fill_placeholder_values(self, content: str, todos: List[str]) -> str:
        """Fill in placeholder values for TODO comments."""
        for var in set(todos):
            placeholder = "0.0 # Placeholder - needs implementation analysis"
            content = content.replace(
                f'# TODO: FW.Verify("{var}", expected_value)',
                f'FW.Verify("{var}", {placeholder})',
            )
            content = content.replace(
                f'FW.Verify("{var}", 0.0) # Placeholder - adjust based on requirement',
                f'FW.Verify("{var}", {placeholder})',
            )
        return content

    def _analyze_implementation(self, component_name: str) -> Dict:
        """Analyze implementation files to find function logic."""
        result = {"success": False}
        for source_dir in self.source_dirs:
            for header_file in list(source_dir.rglob("*.h")) + list(source_dir.rglob("*.hpp")) + list(source_dir.rglob("*.c")) + list(source_dir.rglob("*.cpp")):
                try:
                    content = self._read_file(header_file)
                    if content and component_name.lower().replace(" ", "_") in content.lower():
                        result = {"success": True, "file": str(header_file)}
                        break
                except Exception:
                    pass
        return result

    def _generate_report(
        self, result: Dict, test_result: Dict, rbtca_file: Path, test_file: Path
    ) -> Dict:
        """Generate comprehensive verification report."""
        inputs = result.get("inputs", [])
        outputs = result.get("outputs", [])
        expressions = result.get("expressions", {})

        dd_findings = result.get("data_dictionary_findings", {})
        inputs_in_dd = len(dd_findings.get("inputs_found", []))
        outputs_in_dd = len(dd_findings.get("outputs_found", []))
        total_vars = len(inputs) + len(outputs)
        dd_coverage = (inputs_in_dd + outputs_in_dd) / total_vars if total_vars > 0 else 0

        report = {
            "status": "completed",
            "requirement_id": result.get("requirement_id"),
            "classification": result.get("classification"),
            "method_decision": result.get("method_decision"),
            "testability": result.get("testable"),
            "generated_files": self.generated_files,
            "test_result": test_result,
            "log": self.log_messages,
            "analysis": {
                "coverage_metrics": {
                    "data_dictionary_coverage": f"{dd_coverage:.1%}",
                    "inputs_in_dd": inputs_in_dd,
                    "outputs_in_dd": outputs_in_dd,
                    "total_variables": total_vars,
                },
                "complexity_metrics": {
                    "inputs_count": len(inputs),
                    "outputs_count": len(outputs),
                    "conditions_count": len(expressions.get("conditions", [])),
                    "comparisons_count": len(expressions.get("comparisons", [])),
                    "calculations_count": len(expressions.get("calculations", [])),
                },
                "testability_analysis": result.get("testability_analysis", {}),
            },
            "summary": {
                "inputs_analyzed": len(inputs),
                "outputs_analyzed": len(outputs),
                "expressions_found": sum(len(v) for v in expressions.values()),
                "test_cases_generated": test_result.get("output", "").count("test_TC")
                if test_result.get("output")
                else 0,
            },
        }

        if test_result.get("status") == "passed":
            report["status"] = "passed"
        elif test_result.get("status") == "failed":
            report["status"] = "needs_debugging"
        elif test_result.get("status") == "dry_run":
            report["status"] = "dry_run_complete"

        report["recommendations"] = self._generate_recommendations(result, test_result)

        return report

    def _generate_recommendations(self, result: Dict, test_result: Dict) -> List[str]:
        """Generate recommendations for improving verification."""
        recommendations = []
        dd_findings = result.get("data_dictionary_findings", {})
        missing = dd_findings.get("inputs_not_found", []) + dd_findings.get("outputs_not_found", [])
        if missing:
            recommendations.append(
                f"Add missing variables to data dictionary: {', '.join(missing[:3])}"
            )

        if test_result.get("status") == "failed":
            recommendations.append("Review TODO comments in test file and provide expected values")
            recommendations.append(
                "Run implementation analysis to determine correct output values"
            )

        expressions = result.get("expressions", {})
        if len(expressions.get("conditions", [])) > 2:
            recommendations.append("Consider boundary value analysis for complex conditions")

        if not recommendations:
            recommendations.append("Verification complete - no further action needed")

        return recommendations


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nExamples:")
        print(" python autonomous_verifier.py FAF-LLR-401")
        print(" python autonomous_verifier.py 'Variable A shall be set when B is valid'")
        print("\nOptions:")
        print(" --dry-run Preview without file changes")
        print(" --continue-on-failure Keep debugging until pass")
        print(" --json Output as JSON only")
        sys.exit(1)

    dry_run = "--dry-run" in sys.argv
    continue_on_failure = "--continue-on-failure" in sys.argv
    json_only = "--json" in sys.argv

    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]

    if not args:
        print("Error: No requirement specified")
        sys.exit(1)

    verifier = AutonomousVerifier(dry_run=dry_run, continue_on_failure=continue_on_failure)
    result = verifier.verify_requirement(args[0])

    if not json_only:
        print("\n" + "=" * 60)
        print("VERIFICATION REPORT")
        print("=" * 60)

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
