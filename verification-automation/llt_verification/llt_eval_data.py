from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml_compat as yaml


class RequirementDataMixin:
    def _load_yaml_file(self, path: Path):
        try:
            return yaml.safe_load(path.read_text())
        except Exception:
            return None

    def _strip_source_comments(self, line: str) -> str:
        line = re.sub(r"/\*.*?\*/", "", line)
        line = re.split(r"(?://|#)", line, 1)[0]
        return line.strip()

    def _parse_source_literal(self, raw_value: str) -> Dict[str, object]:
        value = self._strip_source_comments(raw_value).rstrip(",;)")
        parsed: Dict[str, object] = {"value": value, "type": "unknown", "min": None, "max": None}
        if not value:
            return parsed
        if value.lower() in {"true", "false"}:
            boolean_value = value.lower() == "true"
            return {"value": boolean_value, "type": "Boolean", "min": boolean_value, "max": boolean_value}
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            string_value = value[1:-1]
            return {"value": string_value, "type": "String", "min": string_value, "max": string_value}
        try:
            integer_value = int(value, 0)
            return {"value": integer_value, "type": "Integer", "min": integer_value, "max": integer_value}
        except Exception:
            pass
        try:
            float_value = float(value)
            return {"value": float_value, "type": "Float", "min": float_value, "max": float_value}
        except Exception:
            return parsed

    def _split_enum_values(self, raw_value: object) -> List[object]:
        if raw_value is None:
            return []
        if isinstance(raw_value, list):
            items = raw_value
        else:
            text = str(raw_value).strip()
            if not text:
                return []
            text = text.strip("[]{}")
            items = re.split(r"\s*\|\s*|\s*,\s*|\s*;\s*", text)
        values: List[object] = []
        for item in items:
            if item is None:
                continue
            parsed = self._parse_source_literal(str(item)) if not isinstance(item, (bool, int, float)) else {"value": item}
            value = parsed.get("value") if isinstance(parsed, dict) else item
            if value is not None and value not in values:
                values.append(value)
        return values

    def _register_source_term(self, bucket: Dict, entry: Dict[str, object]) -> None:
        name = str(entry.get("name", "")).strip()
        if not name:
            return
        existing = bucket.get(name.lower())
        if existing and existing.get("kind") == "constant" and entry.get("kind") != "constant":
            return
        bucket[name.lower()] = entry

    def _extract_source_constants(self, content: str, source_file: Path):
        patterns = [
            re.compile(r"(?m)^\s*#define\s+([A-Za-z_][A-Za-z0-9_]*)\s+(.+?)\s*$"),
            re.compile(r"(?m)^\s*(?:static\s+)?(?:constexpr\s+)?(?:const\s+)?(?:unsigned\s+|signed\s+)?(?:long\s+long|long|short|int|float|double|bool|char|auto|size_t|uint\d+_t|int\d+_t|[A-Za-z_][A-Za-z0-9_:<>]*)(?:\s*[*&])?\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;]+);"),
        ]
        seen = set()
        for pattern in patterns:
            for match in pattern.finditer(content):
                name = match.group(1).strip()
                raw_value = match.group(2).strip()
                key = (name.lower(), raw_value)
                if key in seen:
                    continue
                seen.add(key)
                yield {
                    "name": name,
                    "kind": "constant",
                    "type": self._parse_source_literal(raw_value).get("type", "unknown"),
                    "value": self._parse_source_literal(raw_value).get("value"),
                    "min": self._parse_source_literal(raw_value).get("min"),
                    "max": self._parse_source_literal(raw_value).get("max"),
                    "raw_value": raw_value,
                    "source": str(source_file),
                }

    def _extract_source_constraints(self, content: str, source_file: Path):
        comparison_pattern = re.compile(
            r"(?P<lhs>[A-Za-z_][A-Za-z0-9_\.>\-\[\]]*)\s*(?P<op><=|>=|==|!=|<|>)\s*(?P<rhs>[-+]?\d+(?:\.\d+)?|[A-Za-z_][A-Za-z0-9_]*)"
        )
        case_pattern = re.compile(r"(?m)^\s*case\s+(?P<value>[-+]?\d+(?:\.\d+)?)\s*:")
        for line_no, raw_line in enumerate(content.splitlines(), 1):
            line = self._strip_source_comments(raw_line)
            if not line:
                continue
            for match in comparison_pattern.finditer(line):
                yield {
                    "source": str(source_file),
                    "line": line_no,
                    "expression": line.strip(),
                    "lhs": match.group("lhs"),
                    "operator": match.group("op"),
                    "rhs": match.group("rhs"),
                    "kind": "comparison",
                }
            for match in case_pattern.finditer(line):
                yield {
                    "source": str(source_file),
                    "line": line_no,
                    "expression": line.strip(),
                    "lhs": "case",
                    "operator": "==",
                    "rhs": match.group("value"),
                    "kind": "case-label",
                }

    def _register_term(self, bucket: Dict, name: str, term_type: str = "unknown", source: str = "", min_val: Optional[str] = None, max_val: Optional[str] = None, extra: Optional[Dict] = None):
        if not name:
            return
        entry = {"name": name, "type": term_type or "unknown", "source": source, "min": min_val, "max": max_val}
        if extra:
            entry.update(extra)
        bucket[name.lower()] = entry

    def _load_csv_terms(self, csv_path: Path, bucket: Dict, source_label: Optional[str] = None):
        try:
            rows = list(csv.reader(csv_path.open("r", newline="")))
        except Exception:
            return
        if not rows:
            return
        header = [c.strip() for c in rows[0]]
        data_rows = rows[1:] if any(header) else rows
        header_l = [h.lower() for h in header]
        is_named = any(k in header_l for k in ("requirementname", "uut name", "verificationidentifier"))
        for row in data_rows:
            if not row:
                continue
            if is_named:
                values = {header_l[i]: row[i].strip() if i < len(row) else "" for i in range(len(header_l))}
                term = values.get("requirementname") or values.get("uut name") or values.get("name") or values.get("verificationidentifier")
                if not term:
                    continue
                self._register_term(
                    bucket,
                    term,
                    term_type=values.get("basedatatype") or values.get("leafdatatype") or values.get("type") or values.get("elementtype") or "unknown",
                    source=source_label or csv_path.name,
                    min_val=values.get("minimum") or values.get("min") or values.get("lower"),
                    max_val=values.get("maximum") or values.get("max") or values.get("upper"),
                    extra=values,
                )
                enum_values = []
                for key in ("enumvalues", "enum_values", "allowedvalues", "allowed_values", "validvalues", "valid_values", "choices", "options", "symbols"):
                    if values.get(key):
                        enum_values.extend(self._split_enum_values(values.get(key)))
                if "enum" in str(values.get("basedatatype") or values.get("leafdatatype") or values.get("type") or values.get("elementtype") or "").lower() or enum_values:
                    bucket[term.lower()].update({"enum_values": enum_values, "valid_values": enum_values, "type": values.get("basedatatype") or values.get("leafdatatype") or values.get("type") or values.get("elementtype") or "Enumeration"})
            else:
                term = row[0].strip() if len(row) > 0 else ""
                if term:
                    self._register_term(
                        bucket,
                        term,
                        term_type=row[1].strip() if len(row) > 1 and row[1].strip() else "unknown",
                        source=source_label or csv_path.name,
                        min_val=row[2].strip() if len(row) > 2 and row[2].strip() else None,
                        max_val=row[3].strip() if len(row) > 3 and row[3].strip() else None,
                    )

    def _load_yaml_terms(self, yaml_path: Path, bucket: Dict, source_label: Optional[str] = None):
        data = self._load_yaml_file(yaml_path)
        if not data:
            return
        items = data.values() if isinstance(data, dict) and all(isinstance(v, dict) for v in data.values()) else data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                term = item.get("RequirementName") or item.get("uut name") or item.get("uut_name") or item.get("name") or item.get("req_name") or item.get("verificationidentifier") or item.get("VerificationIdentifier")
                if term:
                    enum_values = []
                    for key in ("enumValues", "enum_values", "allowedValues", "allowed_values", "validValues", "valid_values", "choices", "options", "symbols"):
                        if item.get(key):
                            enum_values.extend(self._split_enum_values(item.get(key)))
                    self._register_term(
                        bucket,
                        term,
                        term_type=str(item.get("baseDataType") or item.get("base_data_type_name") or item.get("type") or "unknown"),
                        source=source_label or yaml_path.name,
                        min_val=item.get("min") or item.get("minimum"),
                        max_val=item.get("max") or item.get("maximum"),
                        extra=item,
                    )
                    if "enum" in str(item.get("baseDataType") or item.get("base_data_type_name") or item.get("type") or "").lower() or enum_values:
                        bucket[term.lower()].update({"enum_values": enum_values, "valid_values": enum_values, "type": item.get("baseDataType") or item.get("base_data_type_name") or item.get("type") or "Enumeration"})

    def load_data_dictionary_terms(self):
        self.data_dict_terms = {}
        for data_dir in self.data_dict_dirs:
            for csv_path in sorted(data_dir.glob("*.csv")):
                self._load_csv_terms(csv_path, self.data_dict_terms)
            for yaml_path in sorted(data_dir.glob("*.yaml")):
                self._load_yaml_terms(yaml_path, self.data_dict_terms)

    def load_uut_dictionary_terms(self):
        self.uut_dict_terms = {}
        for data_dir in self.procedure_data_dirs:
            for csv_path in sorted(data_dir.glob("uut_dictionary.csv")):
                self._load_csv_terms(csv_path, self.uut_dict_terms, "uut_dictionary.csv")
            for yaml_path in sorted(data_dir.glob("uut_dictionary.yaml")):
                self._load_yaml_terms(yaml_path, self.uut_dict_terms, "uut_dictionary.yaml")

    def load_source_terms(self):
        self.source_terms = {}
        self.source_constants = []
        self.source_constraints = []
        patterns = ("*.h", "*.hpp", "*.c", "*.cpp", "*.m", "*.mm")
        for source_dir in self.source_dirs:
            for pattern in patterns:
                for source_file in source_dir.rglob(pattern):
                    try:
                        content = source_file.read_text(errors="ignore")
                    except Exception:
                        continue
                    for ident in set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", content)):
                        if len(ident) >= 3:
                            self._register_source_term(self.source_terms, {"name": ident, "type": "source file", "source": str(source_file), "kind": "symbol"})
                    for constant_entry in self._extract_source_constants(content, source_file):
                        self._register_source_term(self.source_terms, constant_entry)
                        self.source_constants.append(constant_entry)
                    for constraint_entry in self._extract_source_constraints(content, source_file):
                        self.source_constraints.append(constraint_entry)

    def find_requirement_by_id(self, req_id: str) -> Tuple[Optional[str], Optional[Path]]:
        candidate_files = []
        for req_dir in self.requirement_dirs:
            candidate_files.extend(req_dir.rglob("*.md"))
        for req_file in sorted(set(candidate_files)):
            try:
                content = req_file.read_text(errors="ignore")
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
