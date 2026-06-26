#!/usr/bin/env python3
"""
LLT Verification - Complete workflow for requirement verification

Usage:
 python llt_verification.py FAF-LLR-xxx # Step 1: JSON output with method decision
 python llt_verification.py --step2 FAF-LLR-xxx # Step 2: Formatted output with method decision
 python llt_verification.py "requirement text" # Evaluate description directly
 python llt_verification.py --generate-rbtca FAF-LLR-xxx # Generate RBTCA YAML file
 python llt_verification.py --generate-test FAF-LLR-xxx # Generate test case Python file

Workflow:
 1. Requirement Discovery and Evaluation
 2. Method Decision (Direct/Hybrid based on repo patterns and UUT analysis)
 3. RBTCA Generation (if testable)
 4. Test Case Generation (if testable)
"""

import json
import re
import csv
import sys
import yaml
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from scripts.workspace_utils import candidate_dirs, detect_workspace_root


class RequirementEvaluator:
    """Evaluates requirements for testability."""

    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = detect_workspace_root(workspace_root)
        self.requirement_dirs = candidate_dirs(
            self.workspace_root,
            [
                ("requirements", "LLR"),
                ("requirements", "llr"),
                ("LLR",),
            ],
            fallback_to_root=True,
        )
        self.data_dict_dirs = candidate_dirs(
            self.workspace_root,
            [
                ("requirements", "data_dictionary"),
                ("verification", "test-procedures", "procedure-data"),
            ],
            fallback_to_root=False,
        )
        self.procedure_data_dirs = candidate_dirs(
            self.workspace_root,
            [("verification", "test-procedures", "procedure-data")],
            fallback_to_root=False,
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
        self.test_cases_dirs = candidate_dirs(
            self.workspace_root,
            [("verification", "test-cases", "low_level"), ("verification", "test-cases")],
            fallback_to_root=False,
        )
        self.rbtca_dirs = candidate_dirs(
            self.workspace_root,
            [("records", "rbtca", "low_level"), ("records", "rbtca")],
            fallback_to_root=False,
        )
        self.procedure_vectors_dirs = candidate_dirs(
            self.workspace_root,
            [("verification", "test-procedures", "procedure-vectors")],
            fallback_to_root=False,
        )
        self.data_dict_terms = {}
        self.uut_dict_terms = {}
        self.source_terms = {}
        self.procedure_data_terms = {}

    def _load_yaml_file(self, path: Path):
        try:
            with open(path, "r") as f:
                return yaml.safe_load(f)
        except Exception:
            return None

    def _register_term(
        self,
        bucket: Dict,
        name: str,
        term_type: str = "unknown",
        source: str = "",
        min_val: Optional[str] = None,
        max_val: Optional[str] = None,
        extra: Optional[Dict] = None,
    ):
        if not name:
            return
        key = name.lower()
        entry = {
            "name": name,
            "type": term_type or "unknown",
            "source": source,
            "min": min_val,
            "max": max_val,
        }
        if extra:
            entry.update(extra)
        bucket[key] = entry

    def _load_csv_terms(self, csv_path: Path, bucket: Dict, source_label: Optional[str] = None):
        try:
            with open(csv_path, "r", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
        except Exception:
            return
        if not rows:
            return

        header = [cell.strip() for cell in rows[0]]
        data_rows = rows[1:] if any(h for h in header) else rows
        header_l = [h.lower() for h in header]
        is_named = "requirementname" in header_l or "uut name" in header_l or "verificationidentifier" in header_l

        if is_named:
            for row in data_rows:
                if not row:
                    continue
                values = {header_l[i]: row[i].strip() if i < len(row) else "" for i in range(len(header_l))}
                term = (
                    values.get("requirementname")
                    or values.get("uut name")
                    or values.get("name")
                    or values.get("verificationidentifier")
                )
                if not term:
                    continue
                term_type = (
                    values.get("basedatatype")
                    or values.get("leafdatatype")
                    or values.get("type")
                    or values.get("elementtype")
                    or "unknown"
                )
                min_val = values.get("minimum") or values.get("min") or values.get("lower")
                max_val = values.get("maximum") or values.get("max") or values.get("upper")
                self._register_term(
                    bucket,
                    term,
                    term_type=term_type,
                    source=source_label or csv_path.name,
                    min_val=min_val or None,
                    max_val=max_val or None,
                    extra=values,
                )
            return

        for row in data_rows:
            if not row:
                continue
            term = row[0].strip() if len(row) > 0 else ""
            if not term:
                continue
            term_type = row[1].strip() if len(row) > 1 and row[1].strip() else "unknown"
            min_val = row[2].strip() if len(row) > 2 and row[2].strip() else None
            max_val = row[3].strip() if len(row) > 3 and row[3].strip() else None
            self._register_term(
                bucket,
                term,
                term_type=term_type,
                source=source_label or csv_path.name,
                min_val=min_val,
                max_val=max_val,
            )

    def _load_yaml_terms(self, yaml_path: Path, bucket: Dict, source_label: Optional[str] = None):
        data = self._load_yaml_file(yaml_path)
        if not data:
            return

        if isinstance(data, dict):
            items = data.values() if all(isinstance(v, dict) for v in data.values()) else [data]
        elif isinstance(data, list):
            items = data
        else:
            items = []

        for item in items:
            if not isinstance(item, dict):
                continue
            term = (
                item.get("RequirementName")
                or item.get("uut name")
                or item.get("uut_name")
                or item.get("name")
                or item.get("req_name")
                or item.get("verificationidentifier")
                or item.get("VerificationIdentifier")
            )
            if not term:
                continue
            term_type = item.get("baseDataType") or item.get("base_data_type_name") or item.get("type") or "unknown"
            self._register_term(
                bucket,
                term,
                term_type=str(term_type),
                source=source_label or yaml_path.name,
                min_val=item.get("min") or item.get("minimum"),
                max_val=item.get("max") or item.get("maximum"),
                extra=item,
            )

    def load_data_dictionary_terms(self):
        """Load all terms from data dictionary files."""
        self.data_dict_terms = {}
        for data_dir in self.data_dict_dirs:
            for csv_path in sorted(data_dir.glob("*.csv")):
                self._load_csv_terms(csv_path, self.data_dict_terms)
            for yaml_path in sorted(data_dir.glob("*.yaml")):
                self._load_yaml_terms(yaml_path, self.data_dict_terms)

    def load_uut_dictionary_terms(self):
        """Load UUT dictionary entries for method selection."""
        self.uut_dict_terms = {}
        for data_dir in self.procedure_data_dirs:
            for csv_path in sorted(data_dir.glob("uut_dictionary.csv")):
                self._load_csv_terms(csv_path, self.uut_dict_terms, "uut_dictionary.csv")
            for yaml_path in sorted(data_dir.glob("uut_dictionary.yaml")):
                self._load_yaml_terms(yaml_path, self.uut_dict_terms, "uut_dictionary.yaml")

    def load_source_terms(self):
        """Load terms from source and header files."""
        self.source_terms = {}
        source_patterns = ("*.h", "*.hpp", "*.c", "*.cpp", "*.m", "*.mm")
        for source_dir in self.source_dirs:
            for pattern in source_patterns:
                for source_file in source_dir.rglob(pattern):
                    try:
                        with open(source_file, "r", errors="ignore") as f:
                            content = f.read()
                    except Exception:
                        continue
                    identifiers = set(
                        re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", content)
                    )
                    for ident in identifiers:
                        if len(ident) < 3:
                            continue
                        self.source_terms[ident.lower()] = {
                            "name": ident,
                            "type": "source file",
                            "source": str(source_file),
                        }

    def find_requirement_by_id(self, req_id: str) -> Optional[Tuple[str, Path]]:
        """Find requirement file by ID (e.g., FAF-LLR-401)."""
        candidate_files = []
        for req_dir in self.requirement_dirs:
            candidate_files.extend(req_dir.rglob("*.md"))
        for req_file in sorted(set(candidate_files)):
            try:
                with open(req_file, "r", errors="ignore") as f:
                    content = f.read()
            except Exception:
                continue
            if req_id not in content and req_id not in req_file.name:
                continue
            desc_match = re.search(r"### Description\s*\n\s*\n(.*?)(?:\n###|\Z)", content, re.DOTALL)
            if desc_match:
                return desc_match.group(1).strip(), req_file
            body_match = re.search(r"(?m)^#\s*(.*)$", content)
            if body_match:
                return body_match.group(1).strip(), req_file
            return content.strip(), req_file
        return None, None

    def classify_requirement(self, description: str) -> str:
        """Classify requirement into one of five categories."""
        desc_lower = description.lower()

        math_patterns = [
            r"\b(sum|average|square root|sqrt|sin|cos|tan|exp|power|multiply|divide|add|subtract|calculated)\b",
            r"\b\d+\.?\d*\s*[\+\*\/]\s*\d+\.?\d*\b",
            r"\^|to the power",
        ]
        has_math = any(re.search(p, desc_lower) for p in math_patterns)

        format_patterns = [
            r"\bformat\b",
            r'"[^"]*"',
            r"\bddd\b",
            r"\bmm\b",
            r"/[A-Z]",
            r"°",
        ]
        has_format = any(re.search(p, desc_lower) for p in format_patterns)

        logical_patterns = [
            r"\b(and|or|not|when|if|shall be set|shall be true|shall be false)\b",
            r"==|!=|>=|<=|>|<",
        ]
        has_logical = any(re.search(p, desc_lower) for p in logical_patterns)

        has_where_clause = bool(re.search(r"where\s+\w+\s+(?:is|are)", description, re.IGNORECASE))
        has_format_output = bool(
            re.search(r"formatted\s+as\s+['\"]?[^\s'\"']+['\"]?", description, re.IGNORECASE)
        )
        is_output_format = bool(
            re.search(r"(?:output|set)\s+[\w\s]+\s+as\s+\"[^\"]+\"", description, re.IGNORECASE)
        )
        is_input_format = bool(
            re.search(
                r"(?:input|accept)\s+[\w\s]+\s+(?:in\s+)?(?:one\s+of\s+)?(?:the\s+)?(?:following\s+)?valid\s+formats?",
                description,
                re.IGNORECASE,
            )
        )

        if has_math and has_format:
            return "math expression with string format"
        elif has_format and has_logical and has_where_clause and not is_input_format:
            if is_output_format:
                return "math expression with string format"
            return "logical expression with string format"
        elif has_format and has_format_output and has_where_clause and not is_input_format:
            return "math expression with string format"
        elif has_math:
            return "math expression"
        elif has_format and is_input_format:
            return "string format"
        elif has_format and has_logical:
            return "logical expression with string format"
        elif has_format:
            return "string format"
        elif has_logical:
            return "logical expression"
        else:
            return "logical expression"

    def extract_variables(self, description: str) -> Tuple[List[str], List[str]]:
        """Extract input and output variables from requirement description."""
        inputs = []
        outputs = []

        output_match = re.search(
            r"shall\s+set\s+\*\*([A-Za-z][^*\s]+(?:\s+[A-Za-z][^*\s]+)*?)\s*\*\*\s+as",
            description,
            re.IGNORECASE,
        )
        if output_match:
            term = output_match.group(1).strip()
            if term not in outputs:
                outputs.append(term)

        output_match2 = re.search(
            r"shall\s+set\s+([A-Za-z][^\s,]+(?:\s+[A-Za-z][^\s,]+)*)\s+as\s+follows",
            description,
            re.IGNORECASE,
        )
        if output_match2:
            term = output_match2.group(1).strip()
            if term not in outputs:
                outputs.append(term)

        output_match3 = re.search(
            r"(?:shall\s+)?set\s+(?:the\s+)?\*\*([A-Za-z][^*\s]+(?:\s+[A-Za-z][^*\s]+)*?)\s*\*\*\s+to",
            description,
            re.IGNORECASE,
        )
        if output_match3:
            term = output_match3.group(1).strip()
            if term not in outputs:
                outputs.append(term)

        bold_terms = re.findall(r"\*\*([^*]+?)\*\*", description)

        function_pattern = r"(?:utility|function)\s+shall\s+\*\*([^*]+?)\*\*"
        function_names = re.findall(function_pattern, description, re.IGNORECASE)

        for term in bold_terms:
            term = term.strip()
            if term in outputs:
                continue
            if term in function_names:
                continue
            if re.search(r"\w+\s+\w+\s+To\s+\w+", term):
                continue
            if re.search(r"shall\s+set\s+\*\*" + re.escape(term) + r"\s*\*\*", description, re.IGNORECASE):
                outputs.append(term)
            elif term not in inputs:
                inputs.append(term)

        return inputs, outputs

    def extract_component_name(self, description: str) -> Optional[str]:
        """Extract component name from requirement description."""
        match = re.search(
            r"The\s+\*\*([A-Za-z][A-Za-z0-9_\s]+?)\s*(?:operation|utility|function)?\s*\*\*",
            description,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()

        match = re.search(
            r"\*\*([A-Za-z][A-Za-z0-9_\s]+?)\*\*\s+(?:utility|function|operation)",
            description,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()

        return None

    def check_terms_in_dictionaries(self, terms: List[str]) -> Tuple[List[str], List[str]]:
        """Check which terms are found in data dictionary."""
        found = []
        not_found = []

        for term in terms:
            term_lower = term.lower()
            matched = any(term_lower in t or t in term_lower for t in self.data_dict_terms.keys())
            if matched:
                found.append(term)
            else:
                not_found.append(term)

        return found, not_found

    def get_term_type(self, term: str) -> Optional[str]:
        """Get the type of a term from data dictionary or header files."""
        term_lower = term.lower()
        for dict_term, info in self.data_dict_terms.items():
            if term_lower in dict_term or dict_term in term_lower:
                return info.get("type", "unknown")
        for header_term, info in self.source_terms.items():
            if term_lower in header_term or header_term in term_lower:
                return info.get("type", "header file")
        return None

    def get_term_info(self, term: str) -> Optional[Dict]:
        """Get full info (type, min, max, source) for a term."""
        term_lower = term.lower()
        for dict_term, info in self.data_dict_terms.items():
            if term_lower in dict_term or dict_term in term_lower:
                return info
        for header_term, info in self.uut_dict_terms.items():
            if term_lower in header_term or header_term in term_lower:
                return info
        for header_term, info in self.source_terms.items():
            if term_lower in header_term or header_term in term_lower:
                return info
        return None

    def check_terms_in_headers(self, terms: List[str]) -> Tuple[List[str], List[str]]:
        """Check which terms are found in source/header files."""
        found = []
        not_found = []

        for term in terms:
            term_lower = term.lower()
            matched = any(term_lower in t or t in term_lower for t in self.source_terms.keys())
            if matched:
                found.append(term)
            else:
                not_found.append(term)

        return found, not_found

    def _find_uut_dictionary_matches(self, terms: List[str]) -> Dict[str, List[str]]:
        """Find UUT dictionary entries that relate to the provided terms."""
        found = []
        not_found = []
        for term in terms:
            term_lower = term.lower()
            matched = any(term_lower in t or t in term_lower for t in self.uut_dict_terms.keys())
            if matched:
                found.append(term)
            else:
                not_found.append(term)
        return {"found": found, "not_found": not_found}

    def _lookup_uut_entry(self, component_name: str) -> Optional[Dict]:
        """Return the first UUT dictionary entry that matches the component name."""
        if not component_name:
            return None
        component_lower = component_name.lower()
        for uut_name, info in self.uut_dict_terms.items():
            if component_lower in uut_name or uut_name in component_lower:
                return info
        return None

    def _sample_values_for_term(self, term: str, term_info: Optional[Dict]) -> Dict[str, object]:
        """Produce conservative sample values for a term when exact ranges are missing."""
        term_type = str((term_info or {}).get("type", "")).lower()

        numeric_types = {"float", "double", "real", "int", "integer", "int32", "int64", "uint32", "uint64"}
        boolean_types = {"bool", "boolean"}
        string_types = {"string", "char", "char*"}

        if any(t in term_type for t in boolean_types):
            return {"true": True, "false": False, "nominal": True}

        if any(t in term_type for t in string_types):
            return {"nominal": "VALID", "empty": "", "invalid": "@@@"}

        if any(t in term_type for t in numeric_types):
            min_val = term_info.get("min") if term_info else None
            max_val = term_info.get("max") if term_info else None
            try:
                min_num = float(min_val) if min_val is not None else 0.0
            except Exception:
                min_num = 0.0
            try:
                max_num = float(max_val) if max_val is not None else 1.0
            except Exception:
                max_num = 1.0
            if max_num <= min_num:
                max_num = min_num + 1.0
            return {
                "minimum": min_num,
                "maximum": max_num,
                "below_min": min_num - 1.0,
                "above_max": max_num + 1.0,
                "zero": 0.0,
                "nominal": min_num,
            }

        return {"nominal": 1, "minimum": 0, "maximum": 1, "below_min": -1, "above_max": 2, "zero": 0}

    def _placeholder_expected_literal(self, term_info: Optional[Dict], case_title: str = "") -> str:
        """Return a conservative expected-value literal for generated placeholder tests."""
        term_type = str((term_info or {}).get("type", "")).lower()
        case_lower = case_title.lower()
        if "bool" in term_type or "boolean" in term_type:
            return "False" if "false" in case_lower else "True"
        if "string" in term_type or "char" in term_type:
            return '""'
        return "0.0"

    def extract_expressions(self, description: str) -> Dict[str, List[str]]:
        """Extract logical and mathematical expressions from requirement description."""
        expressions = {
            "conditions": [],
            "comparisons": [],
            "calculations": [],
            "constants": [],
            "robustness_cases": [],
        }

        condition_patterns = [
            r"when\s+\*\*([^*\[]+?)\s*\*\*\s+is\s+greater than\s+(?:\*\*([^*\[]+?)\s*\*\*|(\d+(?:\.\d+)?))",
        ]
        for pattern in condition_patterns:
            matches = re.findall(pattern, description, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple) and len(match) == 3:
                    var = match[0].strip()
                    other_var = match[1].strip() if match[1] else None
                    num_val = match[2].strip() if match[2] else None
                    if other_var:
                        condition = f"{var} > {other_var}"
                    elif num_val:
                        condition = f"{var} > {num_val}"
                    else:
                        condition = f"{var} > 0"
                    expressions["conditions"].append(condition)

        comparison_patterns = [
            r"\*\*([^*\[]+?)\s*\*\*\s+is\s+greater than\s+(?:\*\*([^*\[]+?)\s*\*\*|(\d+(?:\.\d+)?))",
        ]
        for pattern in comparison_patterns:
            matches = re.findall(pattern, description, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple) and len(match) == 3:
                    var = match[0].strip()
                    other_var = match[1].strip() if match[1] else None
                    num_val = match[2].strip() if match[2] else None
                    if other_var:
                        comp = f"{var} > {other_var}"
                    elif num_val:
                        comp = f"{var} > {num_val}"
                    else:
                        comp = f"{var} > 0"
                    expressions["comparisons"].append(comp)

        calc_patterns = [
            r"\([\d\.]+\s+seconds\s*\\?\*\s*\*\*\s*([^*\[]+?)\s*\*\*",
        ]
        for pattern in calc_patterns:
            matches = re.findall(pattern, description, re.IGNORECASE)
            for match in matches:
                if match:
                    calc = f"(0.1 seconds * {match.strip()})"
                    expressions["calculations"].append(calc)

        constant_patterns = [
            r"`([^`]+)`",
            r"\b(?:constant|const)\s+([A-Z0-9_]+)\b",
            r'"([A-Za-z0-9_./-]+)"',
        ]
        for pattern in constant_patterns:
            for match in re.findall(pattern, description, re.IGNORECASE):
                if match and match not in expressions["constants"]:
                    expressions["constants"].append(match.strip())

        robustness_patterns = [
            r"\b(above maximum|below minimum|out of range|null|empty|zero|overflow|underflow|invalid)\b",
        ]
        for pattern in robustness_patterns:
            for match in re.findall(pattern, description, re.IGNORECASE):
                normalized = match.lower().strip()
                if normalized not in expressions["robustness_cases"]:
                    expressions["robustness_cases"].append(normalized)

        return expressions

    def evaluate(self, requirement_description: str, allow_source_reading: bool = False) -> Dict:
        """Main evaluation method."""
        self.load_data_dictionary_terms()
        self.load_uut_dictionary_terms()
        if allow_source_reading:
            self.load_source_terms()
        else:
            self.source_terms = {}

        classification = self.classify_requirement(requirement_description)
        inputs, outputs = self.extract_variables(requirement_description)
        expressions = self.extract_expressions(requirement_description)

        inputs_dict_found, inputs_dict_not_found = self.check_terms_in_dictionaries(inputs)
        outputs_dict_found, outputs_dict_not_found = self.check_terms_in_dictionaries(outputs)

        if allow_source_reading:
            inputs_source_found, inputs_source_not_found = self.check_terms_in_headers(inputs)
            outputs_source_found, outputs_source_not_found = self.check_terms_in_headers(outputs)
        else:
            inputs_source_found, inputs_source_not_found = [], inputs[:]
            outputs_source_found, outputs_source_not_found = [], outputs[:]

        constants = expressions.get("constants", [])
        robustness_cases = expressions.get("robustness_cases", [])

        missing_definitions = []
        if inputs_dict_not_found or outputs_dict_not_found:
            missing_definitions.extend(inputs_dict_not_found + outputs_dict_not_found)

        mapping_evidence = inputs_dict_found or outputs_dict_found or inputs_source_found or outputs_source_found
        can_write_tests = bool((inputs or outputs or constants) and mapping_evidence)

        if not inputs and not outputs:
            can_write_tests = False
            missing_definitions.append("No input or output variables identified")

        blockers = []
        if not (inputs or outputs or constants or expressions.get("conditions") or expressions.get("comparisons") or expressions.get("calculations")):
            blockers.append("No requirement structure identified")
        if not mapping_evidence:
            if allow_source_reading:
                blockers.append("No data dictionary or source evidence to map the requirement")
            else:
                blockers.append("No data dictionary evidence to map the requirement before consulting source code")
        if not can_write_tests:
            blockers.append("No executable verification path could be proven")

        return {
            "classification": classification,
            "testable": can_write_tests,
            "inputs": inputs,
            "outputs": outputs,
            "expressions": expressions,
            "constants": constants,
            "robustness_cases": robustness_cases,
            "data_dictionary_findings": {
                "inputs_found": inputs_dict_found,
                "inputs_not_found": inputs_dict_not_found,
                "outputs_found": outputs_dict_found,
                "outputs_not_found": outputs_dict_not_found,
            },
            "source_file_findings": {
                "inputs_found": inputs_source_found,
                "inputs_not_found": inputs_source_not_found,
                "outputs_found": outputs_source_found,
                "outputs_not_found": outputs_source_not_found,
            },
            "uut_dictionary_findings": self._find_uut_dictionary_matches(inputs + outputs),
            "testability_analysis": {
                "can_write_tests": can_write_tests,
                "reasoning": self._generate_reasoning(
                    classification,
                    inputs,
                    outputs,
                    inputs_dict_found,
                    inputs_dict_not_found,
                    outputs_dict_found,
                    outputs_dict_not_found,
                    inputs_source_found,
                    outputs_source_found,
                    blockers,
                ),
                "missing_definitions": missing_definitions,
                "blockers": blockers,
                "proof_of_testability": self._generate_proof_of_testability(
                    inputs,
                    outputs,
                    inputs_dict_found,
                    inputs_dict_not_found,
                    outputs_dict_found,
                    outputs_dict_not_found,
                    inputs_source_found,
                    outputs_source_found,
                    blockers,
                ),
            },
        }

    def _generate_reasoning(
        self,
        classification: str,
        inputs: List[str],
        outputs: List[str],
        inputs_found: List[str],
        inputs_not_found: List[str],
        outputs_found: List[str],
        outputs_not_found: List[str],
        inputs_source_found: List[str],
        outputs_source_found: List[str],
        blockers: List[str],
    ) -> str:
        """Generate reasoning text."""
        reasoning = f"Classification: {classification}. "

        if inputs:
            reasoning += f"Found {len(inputs_found)}/{len(inputs)} input variables in data dictionary. "
        if outputs:
            reasoning += f"Found {len(outputs_found)}/{len(outputs)} output variables in data dictionary. "

        if inputs_source_found or outputs_source_found:
            reasoning += "Source evidence found for mapping. "

        if not inputs_found and not outputs_found:
            reasoning += "No variables found in data dictionary - requirement may need definition. "
        elif inputs_not_found or outputs_not_found:
            reasoning += "Some variables missing from data dictionary but tests may still be possible. "
        else:
            reasoning += "All variables found - requirement is testable. "

        if blockers:
            reasoning += f"Blockers: {', '.join(blockers)}. "

        return reasoning

    def _generate_proof_of_testability(
        self,
        inputs: List[str],
        outputs: List[str],
        inputs_dict_found: List[str],
        inputs_dict_not_found: List[str],
        outputs_dict_found: List[str],
        outputs_dict_not_found: List[str],
        inputs_source_found: List[str],
        outputs_source_found: List[str],
        blockers: List[str],
    ) -> Dict:
        """Generate proof of testability with detailed analysis."""
        proof = {
            "testable": True,
            "analysis": {
                "inputs": {
                    "defined_in_data_dictionary": inputs_dict_found,
                    "not_in_data_dictionary": inputs_dict_not_found,
                    "found_in_source": inputs_source_found,
                    "count_defined": len(inputs_dict_found),
                    "count_total": len(inputs),
                },
                "outputs": {
                    "defined_in_data_dictionary": outputs_dict_found,
                    "not_in_data_dictionary": outputs_dict_not_found,
                    "found_in_source": outputs_source_found,
                    "count_defined": len(outputs_dict_found),
                    "count_total": len(outputs),
                },
            },
        }

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
            proof["testable"] = True
            proof["reason"] = f"Partially defined: {total_defined}/{total_needed} variables found. Tests can be written for defined variables."
        else:
            proof["testable"] = True
            proof["reason"] = f"All {total_needed} variables found - requirement is fully testable"

        return proof

    def check_repo_pattern(self, component_name: str = None) -> Dict:
        """Collect repo evidence for method selection without making the decision."""
        evidence = {
            "pattern": "unknown",
            "confidence": 0.0,
            "evidence": {},
        }

        rvstest_files = []
        for vectors_dir in self.procedure_vectors_dirs:
            rvstest_files.extend(vectors_dir.rglob("*.rvstest"))
        evidence["evidence"]["rvstest_count"] = len(rvstest_files)

        direct_test_count = 0
        hybrid_test_count = 0
        for test_dir in self.test_cases_dirs:
            for test_file in test_dir.rglob("test_*.py"):
                try:
                    with open(test_file, "r", errors="ignore") as f:
                        content = f.read()
                    if ".rvstest" in content:
                        hybrid_test_count += 1
                    else:
                        direct_test_count += 1
                except Exception:
                    continue

        evidence["evidence"]["hybrid_test_count"] = hybrid_test_count
        evidence["evidence"]["direct_test_count"] = direct_test_count

        matching_uut_entries = []
        if component_name:
            component_lower = component_name.lower()
            for uut_name, info in self.uut_dict_terms.items():
                if component_lower in uut_name or uut_name in component_lower:
                    matching_uut_entries.append(info)
            evidence["evidence"]["component_in_uut_dict"] = bool(matching_uut_entries)
            evidence["evidence"]["matching_uut_entries"] = matching_uut_entries[:5]

            component_lower = component_name.lower()
            evidence["evidence"]["component_is_complex"] = any(
                kw in component_lower for kw in ["queue", "crc", "struct", "pointer", "state"]
            )

        if hybrid_test_count > 0:
            evidence["pattern"] = "hybrid"
            evidence["confidence"] = 0.6
        elif direct_test_count > 0:
            evidence["pattern"] = "direct"
            evidence["confidence"] = 0.6

        return evidence

    def analyze_uut_for_method_decision(self, result: Dict, component_name: Optional[str] = None) -> Dict:
        """Analyze UUT characteristics to determine appropriate method."""
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

        complex_indicators = ["struct", "array", "pointer", "queue", "buffer", "memory", "handle", "context", "instance", "reference"]
        for inp in inputs + outputs:
            inp_lower = inp.lower()
            for indicator in complex_indicators:
                if indicator in inp_lower:
                    analysis["criteria"]["complex_data_types"] = True
                    analysis["reasons"].append(f"Complex data type detected: {indicator}")

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
        """Make final method decision based on repo patterns and UUT analysis."""
        repo_pattern = self.check_repo_pattern(component_name)
        uut_analysis = self.analyze_uut_for_method_decision(result, component_name)

        decision = {
            "selected_method": "unknown",
            "reason": "",
            "evidence": {"repo_pattern": repo_pattern, "uut_analysis": uut_analysis},
            "rejected_modes": {},
        }

        if not result.get("testable", False):
            decision["selected_method"] = "blocked"
            blockers = result.get("testability_analysis", {}).get("blockers", [])
            decision["reason"] = (
                "Blocked: requirement is not testable from the available evidence"
                + (f" ({'; '.join(blockers)})" if blockers else "")
            )
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

    def generate_step2_output(self, result: Dict) -> str:
        """Generate Step 2 formatted output with detailed inputs, expressions, and outputs."""
        lines = []

        lines.append("## Inputs:")
        inputs = result.get("inputs", [])
        data_dict_findings = result.get("data_dictionary_findings", {})
        inputs_header_found = result.get("source_file_findings", {}).get("inputs_found", [])

        if inputs:
            for i, inp in enumerate(inputs, 1):
                term_info = self.get_term_info(inp)
                if term_info:
                    inp_type = term_info.get("type", "unknown")
                    min_val = term_info.get("min") or ""
                    max_val = term_info.get("max") or ""
                    source = term_info.get("source", "data dictionary")
                    if source == "function.csv":
                        inp_type_str = f"function.csv({inp_type})"
                    else:
                        inp_type_str = inp_type
                    lines.append(f"{i}. name: {inp} input type: {inp_type_str} min value: {min_val} max value: {max_val} found in: {source}")
                elif inp in inputs_header_found:
                    lines.append(f"{i}. name: {inp} input type: source file min value: max value: found in: source file")
                else:
                    lines.append(f"{i}. name: {inp} input type: NOT FOUND min value: max value: found in: NOT FOUND")
        else:
            lines.append("No inputs identified.")

        lines.append("\n## Expressions:")
        expressions = result.get("expressions", {})
        all_exprs = expressions.get("conditions", []) + expressions.get("comparisons", []) + expressions.get("calculations", [])
        if all_exprs:
            for i, expr in enumerate(all_exprs, 1):
                lines.append(f"{i}. {expr}")
        else:
            lines.append("No expressions identified.")

        lines.append("\n## Outputs:")
        outputs = result.get("outputs", [])
        outputs_header_found = result.get("source_file_findings", {}).get("outputs_found", [])

        if outputs:
            for i, out in enumerate(outputs, 1):
                term_info = self.get_term_info(out)
                if term_info:
                    out_type = term_info.get("type", "unknown")
                    source = term_info.get("source", "data dictionary")
                    if source == "function.csv":
                        out_type_str = f"function.csv({out_type})"
                    else:
                        out_type_str = out_type
                    lines.append(f"{i}. name: {out} type: {out_type_str} if expression 1 is true (TRUE), Default/ if False(FALSE)")
                elif out in outputs_header_found:
                    lines.append(f"{i}. name: {out} type: source file if expression 1 is true (TRUE), Default/ if False(FALSE)")
                else:
                    lines.append(f"{i}. name: {out} type: NOT FOUND if expression 1 is true (TRUE), Default/ if False(FALSE)")
        else:
            lines.append("No outputs identified.")

        return "\n".join(lines)

    def generate_rbtca_yaml(self, result: Dict, req_id: str) -> Tuple[Dict, Dict]:
        """Generate RBTCA YAML content following the schema. Returns (rbtca_dict, test_case_map)."""
        rbtca = {"inputs": {}, "summary": {"covered_cases": 0, "required_cases": 0, "missing": []}}
        test_case_map = {"inputs": {}, "logic": {}, "math": {}}

        inputs = result.get("inputs", [])
        outputs = result.get("outputs", [])
        expressions = result.get("expressions", {})

        tc_counter = 1
        primary_input = None
        if inputs:
            primary_input = inputs[0]

        if primary_input:
            term_info = self.get_term_info(primary_input)
            sample_values = self._sample_values_for_term(primary_input, term_info)
            inp_type = term_info.get("type", "unknown") if term_info else "unknown"

            rbtca_type = self._map_to_rbtca_type(inp_type)
            input_entry = {"name": primary_input, "type": rbtca_type}
            if rbtca_type == "Boolean":
                input_entry["range"] = {
                    "T": f"test_{req_id}.py:TC{tc_counter:03d}",
                    "F": f"test_{req_id}.py:TC{tc_counter + 1:03d}",
                }
                test_case_map["inputs"][primary_input] = [
                    (f"TC{tc_counter:03d}", "Boolean TRUE case", {"value": sample_values.get("true", True)}),
                    (f"TC{tc_counter + 1:03d}", "Boolean FALSE case", {"value": sample_values.get("false", False)}),
                ]
                tc_counter += 2
            elif rbtca_type in ["Integer", "Float"]:
                input_entry["range"] = {
                    "maximum": f"test_{req_id}.py:TC{tc_counter:03d}",
                    "minimum": f"test_{req_id}.py:TC{tc_counter + 1:03d}",
                }
                input_entry["robustness"] = {
                    "above-max": f"test_{req_id}.py:TC{tc_counter + 2:03d}",
                    "below-min": f"test_{req_id}.py:TC{tc_counter + 3:03d}",
                    "zero": f"test_{req_id}.py:TC{tc_counter + 4:03d}",
                }

                test_case_map["inputs"][primary_input] = [
                    (f"TC{tc_counter:03d}", "Input robustness below minimum", {}),
                    (f"TC{tc_counter + 1:03d}", "Input boundary equal minimum", {}),
                    (f"TC{tc_counter + 2:03d}", "Input independence test", {}),
                    (f"TC{tc_counter + 3:03d}", "Input robustness zero", {}),
                    (f"TC{tc_counter + 4:03d}", "Input robustness above maximum", {}),
                ]
                tc_counter += 5
            else:
                input_entry["range"] = {
                    "nominal": f"test_{req_id}.py:TC{tc_counter:03d}",
                    "alternate": f"test_{req_id}.py:TC{tc_counter + 1:03d}",
                }
                test_case_map["inputs"][primary_input] = [
                    (f"TC{tc_counter:03d}", "Nominal input case", {"value": sample_values.get("nominal", 1)}),
                    (f"TC{tc_counter + 1:03d}", "Alternate input case", {"value": sample_values.get("invalid", sample_values.get("nominal", 1))}),
                ]
                tc_counter += 2

            rbtca["inputs"]["A"] = input_entry

        conditions = expressions.get("conditions", [])
        comparisons = expressions.get("comparisons", [])
        if conditions or comparisons:
            rbtca["logic"] = {}
            expr_idx = 1
            all_conditions = list(set(conditions + comparisons))
            for cond in all_conditions:
                rbtca["logic"][f"EX{expr_idx}"] = {
                    "expression": cond,
                    "conditions": [
                        {
                            "condition": cond,
                            "independence": {
                                "T": f"test_{req_id}.py:TC{tc_counter:03d}",
                                "F": f"test_{req_id}.py:TC{tc_counter + 1:03d}",
                            },
                            "boundary": {
                                "lesser": f"test_{req_id}.py:TC{tc_counter:03d}",
                                "equal": f"test_{req_id}.py:TC{tc_counter + 1:03d}",
                                "greater": f"test_{req_id}.py:TC{tc_counter + 2:03d}",
                            },
                        }
                    ],
                }

                test_case_map["logic"][cond] = [
                    (f"TC{tc_counter:03d}", "Condition TRUE/boundary lesser", {}),
                    (f"TC{tc_counter + 1:03d}", "Condition FALSE/boundary equal", {}),
                    (f"TC{tc_counter + 2:03d}", "Condition TRUE/boundary greater", {}),
                ]
                tc_counter += 3
                expr_idx += 1

        calculations = expressions.get("calculations", [])
        if calculations:
            rbtca["math"] = []
            for calc in calculations:
                rbtca["math"].append(
                    {
                        "expression": calc,
                        "underflow": f"test_{req_id}.py:TC{tc_counter:03d}",
                        "overflow": f"test_{req_id}.py:TC{tc_counter + 1:03d}",
                    }
                )
                test_case_map["math"][calc] = [
                    (f"TC{tc_counter:03d}", "Math underflow case", {}),
                    (f"TC{tc_counter + 1:03d}", "Math overflow case", {}),
                ]
                tc_counter += 2

        rbtca["summary"]["required_cases"] = tc_counter - 1
        rbtca["summary"]["covered_cases"] = tc_counter - 1

        return rbtca, test_case_map

    def generate_test_case_file(
        self,
        result: Dict,
        req_id: str,
        description: str,
        component_name: Optional[str] = None,
    ) -> str:
        """Generate Python test case file content matching RBTCA test cases."""
        _, test_case_map = self.generate_rbtca_yaml(result, req_id)
        inputs = result.get("inputs", [])
        outputs = result.get("outputs", [])
        effective_component = component_name or self.extract_component_name(description) or req_id

        lines = [
            "# Item ID: " + req_id,
            "",
            "import pytest",
            "import pytest_smart as smart",
            "",
            "",
            "@pytest.fixture(autouse=True)",
            "def setUp(FW: smart.FW):",
            f'    FW.Set_Component("{effective_component}")',
            "    FW.Reset()",
            "",
        ]

        tc_counter = 1
        primary_input = None
        for inp in inputs:
            term_info = self.get_term_info(inp)
            if term_info and term_info.get("min") and term_info.get("max"):
                primary_input = inp
                break

        if primary_input:
            term_info = self.get_term_info(primary_input)
            sample_values = self._sample_values_for_term(primary_input, term_info)
            inp_type = self._map_to_rbtca_type(term_info.get("type", "unknown") if term_info else "unknown")

            def add_case(title: str, value, tc_id: int, extra_value=None):
                output_info = [self.get_term_info(out) for out in outputs]
                expected_literals = [self._placeholder_expected_literal(info, title) for info in output_info]
                lines.extend(
                    [
                        "# Purpose:",
                        "# " + primary_input,
                        "# " + title,
                        f"def test_TC{tc_id:03d}(FW: smart.FW):",
                        "    FW.Id(1)",
                        f'    FW.Set("{primary_input}", {repr(value)})',
                        "    FW.Run()",
                    ]
                )
                for out, expected in zip(outputs, expected_literals):
                    lines.append(
                        f'    FW.Verify("{out}", {expected}) # Placeholder - adjust based on requirement'
                    )
                if extra_value is not None:
                    lines.extend(
                        [
                            "",
                            "    FW.Id(2)",
                            f'    FW.Set("{primary_input}", {repr(extra_value)})',
                            "    FW.Run()",
                        ]
                    )
                    for out, expected in zip(outputs, expected_literals):
                        lines.append(
                            f'    FW.Verify("{out}", {expected}) # Placeholder - adjust based on requirement'
                        )
                lines.append("")

            if inp_type == "Boolean":
                add_case("BOOLEAN TRUE CASE", sample_values.get("true", True), tc_counter)
                tc_counter += 1
                add_case("BOOLEAN FALSE CASE", sample_values.get("false", False), tc_counter)
                tc_counter += 1
            elif inp_type in {"Integer", "Float"}:
                add_case(
                    "ROBUSTNESS - BELOW MINIMUM",
                    sample_values.get("maximum", 1.0),
                    tc_counter,
                    sample_values.get("below_min", -1.0),
                )
                tc_counter += 1
                add_case(
                    "BOUNDARY EQUAL TO MINIMUM",
                    sample_values.get("minimum", 0.0),
                    tc_counter,
                    sample_values.get("maximum", 1.0),
                )
                tc_counter += 1
                add_case(
                    "INDEPENDENCE TEST",
                    sample_values.get("minimum", 0.0),
                    tc_counter,
                    sample_values.get("nominal", 1.0),
                )
                tc_counter += 1
                add_case(
                    "ROBUSTNESS - ZERO",
                    sample_values.get("maximum", 1.0),
                    tc_counter,
                    sample_values.get("zero", 0.0),
                )
                tc_counter += 1
                add_case(
                    "ROBUSTNESS - ABOVE MAXIMUM",
                    sample_values.get("minimum", 0.0),
                    tc_counter,
                    sample_values.get("above_max", 2.0),
                )
                tc_counter += 1
            else:
                add_case("NOMINAL CASE", sample_values.get("nominal", "VALID"), tc_counter)
                tc_counter += 1
                add_case(
                    "ALTERNATE CASE",
                    sample_values.get("invalid", sample_values.get("nominal", "VALID")),
                    tc_counter,
                )
                tc_counter += 1

        conditions = result.get("expressions", {}).get("conditions", [])
        comparisons = result.get("expressions", {}).get("comparisons", [])
        all_conditions = list(set(conditions + comparisons))

        for cond in all_conditions:
            lines.extend(
                [
                    "# Purpose:",
                    "# Condition: " + cond,
                    "# TRUE / BOUNDARY LESSER",
                    f"def test_TC{tc_counter:03d}(FW: smart.FW):",
                    "    FW.Id(1)",
                    "    # Set inputs to make condition TRUE",
                ]
            )
            for inp in inputs:
                lines.append(f'    FW.Set("{inp}", 1.0) # Set input for TRUE condition')
            lines.append("    FW.Run()")
            for out in outputs:
                lines.append(f'    FW.Verify("{out}", 0.0) # Placeholder - adjust based on requirement')
            lines.append("")
            tc_counter += 1

            lines.extend(
                [
                    "# Purpose:",
                    "# Condition: " + cond,
                    "# FALSE / BOUNDARY EQUAL",
                    f"def test_TC{tc_counter:03d}(FW: smart.FW):",
                    "    FW.Id(1)",
                    "    # Set inputs to make condition FALSE",
                ]
            )
            for inp in inputs:
                lines.append(f'    FW.Set("{inp}", 0.0) # Set input for FALSE condition')
            lines.append("    FW.Run()")
            for out in outputs:
                lines.append(f'    FW.Verify("{out}", 0.0) # Placeholder - adjust based on requirement')
            lines.append("")
            tc_counter += 1

            lines.extend(
                [
                    "# Purpose:",
                    "# Condition: " + cond,
                    "# TRUE / BOUNDARY GREATER",
                    f"def test_TC{tc_counter:03d}(FW: smart.FW):",
                    "    FW.Id(1)",
                    "    # Set inputs at boundary greater",
                ]
            )
            for inp in inputs:
                lines.append(f'    FW.Set("{inp}", 2.0) # Set input at boundary')
            lines.append("    FW.Run()")
            for out in outputs:
                lines.append(f'    FW.Verify("{out}", 0.0) # Placeholder - adjust based on requirement')
            lines.append("")
            tc_counter += 1

        calculations = result.get("expressions", {}).get("calculations", [])
        for calc in calculations:
            lines.extend(
                [
                    "# Purpose:",
                    "# " + calc,
                    "# ROBUSTNESS: UNDERFLOW VALUE",
                    f"def test_TC{tc_counter:03d}(FW: smart.FW):",
                    "    FW.Id(1)",
                    "    # Set inputs for underflow",
                ]
            )
            for inp in inputs:
                lines.append(f'    FW.Set("{inp}", -1.0) # Underflow value')
            lines.append("    FW.Run()")
            for out in outputs:
                lines.append(f'    FW.Verify("{out}", 0.0) # Placeholder - adjust based on requirement')
            lines.append("")
            tc_counter += 1

            lines.extend(
                [
                    "# Purpose:",
                    "# " + calc,
                    "# ROBUSTNESS: OVERFLOW VALUE",
                    f"def test_TC{tc_counter:03d}(FW: smart.FW):",
                    "    FW.Id(1)",
                    "    # Set inputs for overflow",
                ]
            )
            for inp in inputs:
                lines.append(f'    FW.Set("{inp}", 999999.0) # Overflow value')
            lines.append("    FW.Run()")
            for out in outputs:
                lines.append(f'    FW.Verify("{out}", 0.0) # Placeholder - adjust based on requirement')
            lines.append("")
            tc_counter += 1

        return "\n".join(lines)

    def _map_to_rbtca_type(self, term_type: str) -> str:
        """Map term type to RBTCA data type."""
        type_lower = term_type.lower()
        if type_lower in ["float", "double", "real"]:
            return "Float"
        elif type_lower in ["int", "integer", "int32", "int64", "uint32", "uint64"]:
            return "Integer"
        elif type_lower in ["bool", "boolean"]:
            return "Boolean"
        elif type_lower in ["enum", "enumeration"]:
            return "Enumeration"
        elif type_lower in ["string", "char", "char*"]:
            return "String"
        elif type_lower == "array":
            return "Array"
        elif type_lower in ["struct", "composite"]:
            return "Composite"
        else:
            return "Float"

def verify_requirement(arg: str, step2_mode: bool = False, generate_rbtca: bool = False, generate_test: bool = False) -> None:
    """Verify a requirement by ID or description."""
    is_req_id = bool(re.match(r"FAF-LLR-\d+", arg))

    evaluator = RequirementEvaluator()
    component_name = None
    description = arg

    def _evaluate_with_source_fallback(text: str) -> Dict:
        first_pass = evaluator.evaluate(text, allow_source_reading=False)
        if first_pass.get("testable", False):
            return first_pass
        fallback_pass = evaluator.evaluate(text, allow_source_reading=True)
        if fallback_pass.get("source_file_findings") != first_pass.get("source_file_findings"):
            return fallback_pass
        return fallback_pass

    if is_req_id:
        description, req_path = evaluator.find_requirement_by_id(arg)
        if not description:
            result = {
                "error": f"Requirement {arg} not found",
                "testable": False,
                "reasoning": f"Could not find requirement file for {arg}",
            }
            req_id = arg
        else:
            if not step2_mode and not generate_rbtca and not generate_test:
                print(f"Found requirement: {arg}", file=sys.stderr)
                print(f"File: {req_path}", file=sys.stderr)
            result = _evaluate_with_source_fallback(description)
            result["requirement_id"] = arg
            result["requirement_file"] = str(req_path)
            req_id = arg
            component_name = evaluator.extract_component_name(description)
    else:
        result = _evaluate_with_source_fallback(arg)
        req_id = "unknown"
        component_name = evaluator.extract_component_name(arg)

    result["component_name"] = component_name

    if generate_rbtca and result.get("testable", False):
        rbtca_content, _ = evaluator.generate_rbtca_yaml(result, req_id)
        print(yaml.dump(rbtca_content, default_flow_style=False, sort_keys=False))
    elif generate_test and result.get("testable", False):
        desc = description if is_req_id else arg[:100]
        test_content = evaluator.generate_test_case_file(result, req_id, desc, component_name)
        print(test_content)
    elif step2_mode and result.get("testable", False):
        print(evaluator.generate_step2_output(result))
        method_decision = evaluator.make_method_decision(result, component_name)
        print("\n## Method Decision:")
        print(f"Selected Method: {method_decision['selected_method']}")
        print(f"Reason: {method_decision['reason']}")
        print(f"Repo Pattern: {method_decision['evidence']['repo_pattern']['pattern']} (confidence: {method_decision['evidence']['repo_pattern']['confidence']:.0%})")
    elif step2_mode:
        print("Requirement not testable - Step 2 requires verifiable requirement")
        print(json.dumps(result, indent=2))
    else:
        method_decision = evaluator.make_method_decision(result, component_name)
        result["method_decision"] = method_decision
        if method_decision["selected_method"] == "blocked":
            result["status"] = "blocked"
            result["reason"] = method_decision["reason"]
        print(json.dumps(result, indent=2))


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("LLT Verification - Complete Workflow")
        print("")
        print("Usage: llt_verification.py FAF-LLR-xxx")
        print("    llt_verification.py '<requirement description>'")
        print("    llt_verification.py --step2 FAF-LLR-xxx (for formatted output with method decision)")
        print("    llt_verification.py --generate-rbtca FAF-LLR-xxx (generate RBTCA YAML)")
        print("    llt_verification.py --generate-test FAF-LLR-xxx (generate test case)")
        print("")
        print("Workflow:")
        print(" 1. Requirement Discovery and Evaluation")
        print(" 2. Method Decision (Direct/Hybrid based on repo patterns)")
        print(" 3. RBTCA Generation (if testable)")
        print(" 4. Test Case Generation (if testable)")
        sys.exit(1)

    generate_rbtca = "--generate-rbtca" in sys.argv
    generate_test = "--generate-test" in sys.argv
    step2_mode = "--step2" in sys.argv

    for flag in ["--generate-rbtca", "--generate-test", "--step2"]:
        if flag in sys.argv:
            sys.argv.remove(flag)

    if len(sys.argv) < 2:
        print("Usage: llt_verification.py FAF-LLR-xxx")
        sys.exit(1)

    arg = sys.argv[1]
    verify_requirement(arg, step2_mode, generate_rbtca, generate_test)


if __name__ == "__main__":
    main()
