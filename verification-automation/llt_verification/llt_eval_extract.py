from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from agent_runtime.core import normalize_term


class RequirementExtractMixin:
    def _legacy_prompt_dir(self):
        return self.workspace_root / "references" / "legacy-extraction-prompts"

    def _load_legacy_prompt(self, filename: str) -> str:
        prompt_path = self._legacy_prompt_dir() / filename
        if not prompt_path.exists():
            return ""
        try:
            return prompt_path.read_text(errors="ignore").strip()
        except Exception:
            return ""

    def _run_legacy_prompt(self, poolside_client, stage: str, filename: str, payload: Dict[str, object]) -> Dict[str, object]:
        prompt_text = self._load_legacy_prompt(filename)
        if not prompt_text or poolside_client is None:
            return {}
        try:
            response = poolside_client.complete(stage, payload, instructions=prompt_text)
        except Exception:
            return {}
        parsed = response.get("parsed_content")
        if isinstance(parsed, dict):
            return parsed
        content = response.get("content")
        if isinstance(content, str):
            try:
                loaded = json.loads(content)
                if isinstance(loaded, dict):
                    return loaded
            except Exception:
                return {}
        return {}

    def _merge_unique_strings(self, current: List[str], additions) -> List[str]:
        if not additions:
            return current
        merged = list(current)
        if isinstance(additions, str):
            additions = [additions]
        for item in additions:
            value = str(item).strip()
            if value and value not in merged:
                merged.append(value)
        return merged

    def _merge_types_and_ranges(self, current: List[Dict[str, object]], additions) -> List[Dict[str, object]]:
        if not additions:
            return current
        merged = list(current)
        seen = {str(item.get("name", "")).strip().lower() for item in merged if isinstance(item, dict)}
        if isinstance(additions, dict):
            additions = [additions]
        for item in additions:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            merged.append(item)
            seen.add(key)
        return merged

    def _dedupe_preserve_order(self, values):
        if not values:
            return []
        if isinstance(values, str):
            values = [values]
        result = []
        seen = set()
        for item in values:
            if isinstance(item, dict):
                key = json.dumps(item, sort_keys=True, default=str)
            else:
                key = str(item).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    def _normalize_string_list(self, values: List[str]) -> List[str]:
        return [str(item).strip() for item in self._dedupe_preserve_order(values) if str(item).strip()]

    def _normalize_types_and_ranges(self, items: List[Dict[str, object]]) -> List[Dict[str, object]]:
        normalized: List[Dict[str, object]] = []
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized_item = {
                "name": name,
                "type": str(item.get("type") or item.get("type_hint") or "unknown").strip() or "unknown",
                "role": str(item.get("role") or "").strip(),
                "section": str(item.get("section") or "").strip(),
                "data_source": str(item.get("data_source") or item.get("source") or "requirement text").strip(),
                "min": item.get("min"),
                "max": item.get("max"),
                "valid_values": self._normalize_string_list(item.get("valid_values", [])),
                "invalid_values": self._normalize_string_list(item.get("invalid_values", [])),
                "default": item.get("default"),
                "constraints": self._normalize_string_list(item.get("constraints", [])),
            }
            normalized.append(normalized_item)
        return normalized

    def _normalize_expressions(self, expressions: Dict[str, List[str]]) -> Dict[str, List[str]]:
        return {
            key: self._normalize_string_list(expressions.get(key, []))
            for key in ("conditions", "comparisons", "calculations", "constants", "robustness_cases")
        }

    def _term_aliases(self, term: str) -> List[str]:
        text = str(term or "").strip()
        if not text:
            return []
        lowered = text.lower()
        compact = re.sub(r"[^a-z0-9]+", "", lowered)
        spaced = re.sub(r"[^a-z0-9]+", " ", lowered).strip()
        snake = normalize_term(text)
        variants = [text, lowered, spaced, compact, snake, snake.replace("_", " ")]
        return self._normalize_string_list(variants)

    def _requirement_signals(self, description: str) -> Dict[str, bool]:
        lowered = description.lower()
        return {
            "math": bool(re.search(r"\b(sum|average|square root|sqrt|sin|cos|tan|exp|power|multiply|divide|add|subtract|calculated|formula|ratio|proportion)\b|[\+\-\*/^]", lowered)),
            "format": bool(re.search(r"\bformat\b|\bformatted\b|\bleading zeros\b|\bleading spaces\b|\bstring format\b|\bvalid formats?\b", lowered)),
            "logical": bool(re.search(r"\b(and|or|not|when|if|unless|only if|shall be set|shall be true|shall be false)\b|==|!=|>=|<=|>|<", lowered)),
        }

    def _needs_classification_fallback(self, classification: str, description: str) -> bool:
        signals = self._requirement_signals(description)
        lower_classification = (classification or "").lower()
        if signals["math"] and "math" not in lower_classification:
            return True
        if signals["format"] and "format" not in lower_classification:
            return True
        return False

    def _build_extraction_contract(
        self,
        requirement_description: str,
        classification: str,
        inputs: List[str],
        outputs: List[str],
        bold_terms: List[str],
        types_and_ranges: List[Dict[str, object]],
        expressions: Dict[str, List[str]],
        legacy_prompt_used: List[str],
        notes: List[str],
    ) -> Dict[str, object]:
        signals = self._requirement_signals(requirement_description)
        alias_terms = self._normalize_string_list(inputs + outputs + bold_terms + [item.get("name", "") for item in types_and_ranges if isinstance(item, dict)])
        aliases = {
            term: {
                "normalized": normalize_term(term),
                "dd_name": f"dd_{normalize_term(term)}",
                "variants": self._term_aliases(term),
            }
            for term in alias_terms
        }
        gaps = []
        if not inputs:
            gaps.append("inputs")
        if not outputs:
            gaps.append("outputs")
        if not types_and_ranges:
            gaps.append("types_and_ranges")
        if signals["math"] and not expressions.get("calculations"):
            gaps.append("math_expressions")
        if signals["format"] and not types_and_ranges:
            gaps.append("format_details")
        if self._needs_classification_fallback(classification, requirement_description):
            gaps.append("classification")
        contract = {
            "classification": classification,
            "bold_terms": self._normalize_string_list(bold_terms),
            "inputs": self._normalize_string_list(inputs),
            "outputs": self._normalize_string_list(outputs),
            "types_and_ranges": self._normalize_types_and_ranges(types_and_ranges),
            "expressions": self._normalize_expressions(expressions),
            "aliases": aliases,
            "gaps": self._normalize_string_list(gaps),
            "legacy_prompt_used": self._normalize_string_list(legacy_prompt_used),
            "notes": self._normalize_string_list(notes),
        }
        return contract

    def _looks_like_type_name(self, text: str) -> bool:
        lowered = text.lower().strip()
        return any(token in lowered for token in ["integer", "float", "boolean", "enum", "enumeration", "string", "char", "array", "struct", "pointer", "function", "composite"])

    def _parse_range_hint(self, text: str) -> Dict[str, Optional[str]]:
        result: Dict[str, Optional[str]] = {"min": None, "max": None, "valid_values": None, "invalid_values": None, "default": None}
        if not text:
            return result
        range_match = re.search(r"between\s+([-\w\.]+)\s+and\s+([-\w\.]+)", text, re.IGNORECASE) or re.search(r"from\s+([-\w\.]+)\s+(?:to|through|-)\s+([-\w\.]+)", text, re.IGNORECASE) or re.search(r"range\s*[:=]?\s*([-\w\.]+)\s*(?:to|-|\.{2,})\s*([-\w\.]+)", text, re.IGNORECASE)
        if range_match:
            result["min"], result["max"] = range_match.group(1), range_match.group(2)
        min_match = re.search(r"\bmin(?:imum)?\s*[:=]?\s*([-\w\.]+)", text, re.IGNORECASE)
        max_match = re.search(r"\bmax(?:imum)?\s*[:=]?\s*([-\w\.]+)", text, re.IGNORECASE)
        if min_match:
            result["min"] = min_match.group(1)
        if max_match:
            result["max"] = max_match.group(1)
        values_match = re.search(r"(?:valid|allowed|enum|choices?|options?)\s*values?\s*[:=]?\s*(.+)$", text, re.IGNORECASE)
        if values_match:
            result["valid_values"] = [v.strip() for v in re.split(r"[|,;/]", values_match.group(1)) if v.strip()]
        invalid_match = re.search(r"invalid\s*values?\s*[:=]?\s*(.+)$", text, re.IGNORECASE)
        if invalid_match:
            result["invalid_values"] = [v.strip() for v in re.split(r"[|,;/]", invalid_match.group(1)) if v.strip()]
        default_match = re.search(r"default\s*[:=]?\s*([-\w\.]+)", text, re.IGNORECASE)
        if default_match:
            result["default"] = default_match.group(1)
        return result

    def extract_types_and_ranges(self, description: str) -> List[Dict[str, object]]:
        items: List[Dict[str, object]] = []
        current: Dict[str, object] = {}
        section = ""
        table_headers: List[str] = []

        def commit():
            nonlocal current
            if not current:
                return
            name = str(current.get("name", "")).strip()
            if not name:
                current = {}
                return
            lowered = name.lower()
            if not current.get("role"):
                if any(k in lowered for k in ["return", "output", "result", "status", "success"]):
                    current["role"] = "output"
                elif any(k in lowered for k in ["input", "parameter", "argument", "element", "value", "size", "count", "number", "mode", "direction"]):
                    current["role"] = "input"
            if current.get("type") is None and current.get("type_hint"):
                current["type"] = current["type_hint"]
            items.append(current)
            current = {}

        for raw_line in list(description.splitlines()) + [""]:
            line = raw_line.strip()
            lower = line.lower()
            if not line:
                commit()
                table_headers = []
                continue
            if lower.startswith("## "):
                heading = lower[3:].strip()
                section = heading
                continue
            if lower in {"inputs", "input", "outputs", "output", "types and ranges", "expressions"}:
                section = lower
                continue
            if line.startswith("|") and line.count("|") >= 2:
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                if not table_headers and any(self._looks_like_type_name(cell) or cell.lower() in {"name", "type", "min", "max", "data source", "source", "range", "valid values", "invalid values"} for cell in cells):
                    table_headers = [cell.lower() for cell in cells]
                    continue
                if table_headers and len(cells) >= 2:
                    commit()
                    item: Dict[str, object] = {"section": section}
                    for idx, header in enumerate(table_headers):
                        if idx >= len(cells):
                            continue
                        value = cells[idx]
                        if not value:
                            continue
                        if header in {"name", "requirement", "signal", "term", "variable"}:
                            item["name"] = value
                        elif header in {"type"}:
                            item["type"] = value
                        elif header in {"min", "minimum"}:
                            item["min"] = value
                        elif header in {"max", "maximum"}:
                            item["max"] = value
                        elif header in {"data source", "source"}:
                            item["data_source"] = value
                        elif header in {"range"}:
                            item.update(self._parse_range_hint(value))
                        elif "valid" in header or "allowed" in header or "enum" in header:
                            item["valid_values"] = [v.strip() for v in re.split(r"[|,;/]", value) if v.strip()]
                    if item.get("name"):
                        items.append(item)
                    continue
            field_match = re.match(r"^(?:[-*•]\s*)?([A-Za-z][A-Za-z0-9 _/().-]{1,60}?)\s*:\s*(.+)$", line)
            if field_match:
                key = field_match.group(1).strip()
                value = field_match.group(2).strip()
                key_lower = key.lower()
                if key_lower in {"name", "requirement name", "term", "signal", "input", "output", "variable"}:
                    commit()
                    current = {"name": value, "section": section}
                    if key_lower in {"output"} or section == "output":
                        current["role"] = "output"
                    elif key_lower in {"input"} or section == "input":
                        current["role"] = "input"
                    continue
                if not current:
                    current = {"name": key, "section": section}
                if key_lower in {"type", "datatype", "base data type", "base_data_type_name", "leafdatatype"}:
                    current["type"] = value
                    current["type_hint"] = value
                elif key_lower in {"min", "minimum"}:
                    current["min"] = value
                elif key_lower in {"max", "maximum"}:
                    current["max"] = value
                elif key_lower in {"range"}:
                    current.update(self._parse_range_hint(value))
                elif key_lower in {"data source", "source", "testbot source"}:
                    current["data_source"] = value
                elif "valid" in key_lower or "allowed" in key_lower or "enum" in key_lower:
                    current["valid_values"] = [v.strip() for v in re.split(r"[|,;/]", value) if v.strip()]
                elif "invalid" in key_lower:
                    current["invalid_values"] = [v.strip() for v in re.split(r"[|,;/]", value) if v.strip()]
                elif "default" in key_lower:
                    current["default"] = value
                elif "constraint" in key_lower or "comparison" in key_lower:
                    current.setdefault("constraints", []).append(value)
                else:
                    current.setdefault("notes", []).append(f"{key}: {value}")
                continue
            if not current:
                current = {"name": line, "section": section}
                continue
            if not current.get("name"):
                current["name"] = line
                continue
            current.setdefault("notes", []).append(line)
            range_hint = self._parse_range_hint(line)
            if range_hint.get("min") is not None:
                current["min"] = range_hint["min"]
            if range_hint.get("max") is not None:
                current["max"] = range_hint["max"]
            if range_hint.get("valid_values"):
                current.setdefault("valid_values", []).extend(range_hint["valid_values"])
            if range_hint.get("invalid_values"):
                current.setdefault("invalid_values", []).extend(range_hint["invalid_values"])
            if range_hint.get("default") is not None:
                current["default"] = range_hint["default"]
            if self._looks_like_type_name(line) and "type" not in current:
                current["type"] = line
                current["type_hint"] = line
        commit()
        for item in items:
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            valid_values = item.get("valid_values")
            invalid_values = item.get("invalid_values")
            if isinstance(valid_values, list) and valid_values:
                item["valid_values"] = list(dict.fromkeys(valid_values))
            if isinstance(invalid_values, list) and invalid_values:
                item["invalid_values"] = list(dict.fromkeys(invalid_values))
        return items

    def classify_requirement(self, description: str) -> str:
        d = description.lower()
        m = any(re.search(p, d) for p in [r"\b(sum|average|square root|sqrt|sin|cos|tan|exp|power|multiply|divide|add|subtract|calculated)\b", r"\b\d+\.?\d*\s*[\+\*\/]\s*\d+\.?\d*\b", r"\^|to the power"])
        f = any(re.search(p, d) for p in [r"\bformat\b", r'"[^"]*"', r"\bddd\b", r"\bmm\b", r"/[A-Z]", r"°"])
        l = any(re.search(p, d) for p in [r"\b(and|or|not|when|if|shall be set|shall be true|shall be false)\b", r"==|!=|>=|<=|>|<"])
        w = bool(re.search(r"where\s+\w+\s+(?:is|are)", description, re.IGNORECASE))
        fo = bool(re.search(r"formatted\s+as\s+['\"]?[^\s'\"]+['\"]?", description, re.IGNORECASE))
        oo = bool(re.search(r"(?:output|set)\s+[\w\s]+\s+as\s+\"[^\"]+\"", description, re.IGNORECASE))
        ii = bool(re.search(r"(?:input|accept)\s+[\w\s]+\s+(?:in\s+)?(?:one\s+of\s+)?(?:the\s+)?(?:following\s+)?valid\s+formats?", description, re.IGNORECASE))
        if m and f:
            return "math expression with string format"
        if f and l and w and not ii:
            return "math expression with string format" if oo else "logical expression with string format"
        if f and fo and w and not ii:
            return "math expression with string format"
        if m:
            return "math expression"
        if f and ii:
            return "string format"
        if f and l:
            return "logical expression with string format"
        return "string format" if f else ("logical expression" if l else "logical expression")

    def extract_variables(self, description: str) -> Tuple[List[str], List[str]]:
        inputs, outputs = [], []
        for pat in [
            r"shall\s+set\s+\*\*([A-Za-z][^*\s]+(?:\s+[A-Za-z][^*\s]+)*?)\s*\*\*\s+as",
            r"shall\s+set\s+([A-Za-z][^\s,]+(?:\s+[A-Za-z][^\s,]+)*)\s+as\s+follows",
            r"(?:shall\s+)?set\s+(?:the\s+)?\*\*([A-Za-z][^*\s]+(?:\s+[A-Za-z][^*\s]+)*?)\s*\*\*\s+to",
        ]:
            m = re.search(pat, description, re.IGNORECASE)
            if m and m.group(1).strip() not in outputs:
                outputs.append(m.group(1).strip())
        bold_terms = re.findall(r"\*\*([^*]+?)\*\*", description)
        fn_names = re.findall(r"(?:utility|function)\s+shall\s+\*\*([^*]+?)\*\*", description, re.IGNORECASE)
        for term in bold_terms:
            term = term.strip()
            if term and term not in outputs and term not in fn_names and not re.search(r"\w+\s+\w+\s+To\s+\w+", term):
                if re.search(r"shall\s+set\s+\*\*" + re.escape(term) + r"\s*\*\*", description, re.IGNORECASE):
                    outputs.append(term)
                elif term not in inputs:
                    inputs.append(term)
        for item in self.extract_types_and_ranges(description):
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            role = str(item.get("role", "")).lower()
            if role == "output" or any(k in name.lower() for k in ["return", "output", "result", "status", "success"]):
                if name not in outputs:
                    outputs.append(name)
            else:
                if name not in inputs and name not in outputs:
                    inputs.append(name)
        return inputs, outputs

    def extract_bold_terms(self, description: str) -> List[str]:
        terms = []
        for term in re.findall(r"\*\*([^*]+?)\*\*", description):
            cleaned = term.strip()
            if cleaned and cleaned not in terms:
                terms.append(cleaned)
        return terms

    def extract_component_name(self, description: str) -> Optional[str]:
        for pat in [r"The\s+\*\*([A-Za-z][A-Za-z0-9_\s]+?)\s*(?:operation|utility|function)?\s*\*\*", r"\*\*([A-Za-z][A-Za-z0-9_\s]+?)\*\*\s+(?:utility|function|operation)"]:
            m = re.search(pat, description, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None

    def extract_expressions(self, description: str) -> Dict[str, List[str]]:
        expressions = {"conditions": [], "comparisons": [], "calculations": [], "constants": [], "robustness_cases": []}
        for pat in [r"when\s+\*\*([^*\[]+?)\s*\*\*\s+is\s+greater than\s+(?:\*\*([^*\[]+?)\s*\*\*|(\d+(?:\.\d+)?))"]:
            for match in re.findall(pat, description, re.IGNORECASE):
                if len(match) == 3:
                    expressions["conditions"].append(f"{match[0].strip()} > {(match[1].strip() if match[1] else match[2].strip() if match[2] else '0')}")
        for pat in [r"\*\*([^*\[]+?)\s*\*\*\s+is\s+greater than\s+(?:\*\*([^*\[]+?)\s*\*\*|(\d+(?:\.\d+)?))"]:
            for match in re.findall(pat, description, re.IGNORECASE):
                if len(match) == 3:
                    expressions["comparisons"].append(f"{match[0].strip()} > {(match[1].strip() if match[1] else match[2].strip() if match[2] else '0')}")
        for match in re.findall(r"\([\d\.]+\s+seconds\s*\\?\*\s*\*\*\s*([^*\[]+?)\s*\*\*", description, re.IGNORECASE):
            if match:
                expressions["calculations"].append(f"(0.1 seconds * {match.strip()})")
        for pat in [r"`([^`]+)`", r"\b(?:constant|const)\s+([A-Z0-9_]+)\b", r'"([A-Za-z0-9_./-]+)"']:
            for match in re.findall(pat, description, re.IGNORECASE):
                if match and match.strip() not in expressions["constants"]:
                    expressions["constants"].append(match.strip())
        for match in re.findall(r"\b(above maximum|below minimum|out of range|null|empty|zero|overflow|underflow|invalid)\b", description, re.IGNORECASE):
            normalized = match.lower().strip()
            if normalized not in expressions["robustness_cases"]:
                expressions["robustness_cases"].append(normalized)
        return expressions
