#!/usr/bin/env python3
"""
Testcase Generator Agent

Consumes the structured JSON produced by bolded_terms_extractor.py and
generates a Python testcase file for the detected requirement.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Tuple


def normalize_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def sanitize_identifier(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", text or "").strip("_")
    return cleaned or "generated"


def framework_label(item: Dict[str, Any]) -> str:
    name = (item.get("data_dictionary_term") or item.get("name") or "").strip()
    if not name:
        return "Unknown"
    if ": " in name:
        name = name.split(": ", 1)[-1]
    name = name.replace(":", " ")
    return re.sub(r"\s+", " ", name).strip()


def state_framework_label(item: Dict[str, Any]) -> str:
    verification_identifier = str(item.get("verification_identifier") or "")
    label = framework_label(item)
    field = ""

    if verification_identifier:
        tail = verification_identifier.split(".", 1)[-1]
        field = tail.split("[", 1)[0].strip()
        field = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", field)
        field = field.replace("_", " ")
        field = re.sub(r"\s+", " ", field).strip().title()

    root = verification_identifier.split("[", 1)[0].split(".", 1)[0].strip()
    root = root[:1].upper() + root[1:] if root else ""

    if root and field:
        return f"{root} {field}"
    if root and root.lower() not in normalize_key(label):
        return f"{root} {label}"
    return label


def normalized_type(item: Dict[str, Any]) -> str:
    return str(item.get("type") or item.get("type_name") or "").strip().lower()


def type_metadata(item: Dict[str, Any]) -> Dict[str, Any]:
    return dict(item.get("type_metadata") or {})


def parse_semicolon_values(value: str) -> List[str]:
    return [part.strip() for part in (value or "").split(";") if part.strip()]


def first_matching_key(keys: List[str], candidates: List[str]) -> str:
    for candidate in candidates:
        candidate_key = normalize_key(candidate)
        for key in keys:
            if key == candidate_key or key in candidate_key or candidate_key in key:
                return key
    return ""


def python_literal(value: Any) -> str:
    if isinstance(value, str):
        return repr(value)
    if value is None:
        return "None"
    return repr(value)


def sample_array_literal(item: Dict[str, Any], expression_text: str) -> str:
    meta = type_metadata(item)
    subtype = str(meta.get("array_subtype_kind") or meta.get("array_subtype") or "integer_const").lower()
    length = meta.get("array_length")
    try:
        count = int(length)
    except Exception:
        count = 1
    count = max(1, min(count, 3))

    if "boolean" in subtype:
        element = "True"
    elif "float" in subtype:
        element = "1.0"
    elif "string" in subtype:
        element = repr("A")
    elif "enum" in subtype:
        values = parse_semicolon_values(str(meta.get("enum_values") or ""))
        element = repr(values[0]) if values else repr("VALUE")
    else:
        element = "1"

    return "[" + ", ".join([element] * count) + "]"


def sample_input_literal(item: Dict[str, Any], expression_text: str) -> str:
    type_name = normalized_type(item)
    meta = type_metadata(item)
    label = normalize_key(framework_label(item))
    expr = normalize_key(expression_text)

    if type_name in {"bool", "boolean"}:
        if any(token in expr for token in ["not ", "false", "fail", "invalid", "unsuccessful", "disabled"]):
            return "False"
        return "True"

    if meta.get("array_subtype") or type_name == "array":
        return sample_array_literal(item, expression_text)

    if "pointer" in type_name or "*" in str(item.get("type") or item.get("type_name") or "") or "reference" in label:
        return "object()"

    if "string" in type_name or meta.get("string_length"):
        return repr("VALID")

    if meta.get("enum_values") or "enum" in type_name or "state" in type_name:
        values = parse_semicolon_values(str(meta.get("enum_values") or ""))
        if values:
            preferred = first_matching_key(values, ["valid", "success", "true", "enabled", "on", "ready"])
            return repr(preferred or values[0])
        return repr("VALUE")

    if "float" in type_name or "double" in type_name:
        return "1.0"

    if any(token in type_name for token in ["int8_t", "uint8_t", "int16_t", "uint16_t", "int32_t", "uint32_t", "int64_t", "uint64_t"]):
        if any(token in expr for token in ["zero", " == 0", "equal to zero"]):
            return "0"
        return "1"

    if "int" in type_name or "integer" in type_name:
        if any(token in expr for token in ["zero", " == 0", "equal to zero"]):
            return "0"
        if any(token in expr for token in ["non zero", "non-zero", "> 0", "greater than zero"]):
            return "1"
        min_value = meta.get("min_value")
        if isinstance(min_value, int) and min_value > 0:
            return str(min_value)
        return "1"

    return "1"


def input_sample_map(inputs: List[Dict[str, Any]], expression_text: str) -> Dict[str, str]:
    samples: Dict[str, str] = {}
    for item in inputs:
        samples[normalize_key(framework_label(item))] = sample_input_literal(item, expression_text)
    return samples


def derive_state_expected_value(
    item: Dict[str, Any],
    values_by_label: Dict[str, str],
) -> Tuple[str, str | None]:
    type_name = normalized_type(item)
    label = normalize_key(framework_label(item))
    verification_identifier = str(item.get("verification_identifier") or "")
    verification_tail = normalize_key(verification_identifier.split(".")[-1])

    if label in values_by_label:
        value = values_by_label[label]
        if value == "None":
            return "None", "!="
        return value, None

    if verification_tail in {"capacity", "elementsize", "mutexcounter"}:
        for candidate in (["maximum number of elements", "capacity"] if verification_tail == "capacity" else ["element size"] if verification_tail == "elementsize" else ["mutex counter"]):
            match_key = first_matching_key(list(values_by_label.keys()), [candidate])
            if match_key:
                return values_by_label[match_key], None

    if "pointer" in type_name or "*" in str(item.get("type") or item.get("type_name") or ""):
        return "None", "!="

    if any(token in label for token in ["mutex counter", "count", "head", "tail"]):
        return "0", None

    if "allocated memory buffer" in label or verification_tail in {"allocatedmemorybuffer", "mutex"}:
        return "None", "!="

    if "capacity" in label or verification_tail == "capacity":
        for candidate in ["maximum number of elements", "capacity"]:
            match_key = first_matching_key(list(values_by_label.keys()), [candidate])
            if match_key:
                return values_by_label[match_key], None

    if "element size" in label or verification_tail == "elementsize":
        match_key = first_matching_key(list(values_by_label.keys()), ["element size"])
        if match_key:
            return values_by_label[match_key], None

    if label in values_by_label:
        return values_by_label[label], None

    if any(token in type_name for token in ["int", "integer", "uint", "int8_t", "uint8_t", "int16_t", "uint16_t", "int32_t", "uint32_t", "int64_t", "uint64_t"]):
        return "0", None
    if "float" in type_name or "double" in type_name:
        return "0.0", None
    if type_name in {"bool", "boolean"}:
        return "False", None
    return "None", "!="


def expected_output_value(item: Dict[str, Any], expression: Dict[str, str]) -> Tuple[str, str | None]:
    type_name = normalized_type(item)
    label = normalize_key(framework_label(item))
    expr_text = normalize_key(expression.get("source_text") or expression.get("alias_expression") or "")
    output_label = normalize_key(expression.get("output") or "")
    metadata = type_metadata(item)

    if "pointer" in type_name or "*" in str(item.get("type") or item.get("type_name") or ""):
        return "None", "!="

    if type_name in {"bool", "boolean"}:
        if any(token in expr_text or token in output_label or token in label for token in ["fail", "invalid", "unsuccessful", "false", "not "]):
            return "False", None
        return "True", None

    if metadata.get("enum_values") or "enum" in type_name or "state" in type_name:
        values = parse_semicolon_values(str(metadata.get("enum_values") or ""))
        if values:
            preferred = first_matching_key(values, ["success", "valid", "true", "ready", "ok"])
            return repr(preferred or values[0]), None
        return repr("VALUE"), None

    if "float" in type_name or "double" in type_name:
        return "1.0", None

    if any(token in type_name for token in ["int8_t", "uint8_t", "int16_t", "uint16_t", "int32_t", "uint32_t", "int64_t", "uint64_t", "int", "integer"]):
        if any(token in label for token in ["count", "size", "capacity", "counter", "head", "tail"]):
            return "0", None
        return "1", None

    return "None", "!="


def invalid_enum_literal(item: Dict[str, Any]) -> str:
    metadata = type_metadata(item)
    values = parse_semicolon_values(str(metadata.get("enum_values") or ""))
    invalid_candidates = ["Invalid", "Error", "Failure", "Unknown", "Not Set"]
    for candidate in invalid_candidates:
        if candidate not in values:
            return repr(candidate)
    return repr("Invalid")


def scenario_input_literal(item: Dict[str, Any], scenario: str, requirement_name: str) -> str:
    type_name = normalized_type(item)
    metadata = type_metadata(item)
    expr_context = requirement_name

    if scenario == "positive":
        return sample_input_literal(item, expr_context)

    if scenario == "boundary":
        if type_name in {"bool", "boolean"}:
            return "True"
        if metadata.get("array_subtype") or type_name == "array":
            return sample_array_literal(item, expr_context)
        if "pointer" in type_name or "*" in str(item.get("type") or item.get("type_name") or "") or metadata.get("pointer_values"):
            return "object()"
        if metadata.get("enum_values") or "enum" in type_name or "state" in type_name:
            values = parse_semicolon_values(str(metadata.get("enum_values") or ""))
            return repr(values[0]) if values else repr("VALUE")
        if "string" in type_name or metadata.get("string_length"):
            return repr("A")
        if "float" in type_name or "double" in type_name:
            min_value = metadata.get("min_value")
            if isinstance(min_value, (int, float)):
                if min_value == 0:
                    return "1.0"
                return str(min_value)
            return "1.0"
        if any(token in type_name for token in ["int8_t", "uint8_t", "int16_t", "uint16_t", "int32_t", "uint32_t", "int64_t", "uint64_t", "int", "integer"]):
            min_value = metadata.get("min_value")
            if isinstance(min_value, int):
                if min_value == 0:
                    return "1"
                return str(min_value)
            return "1"
        return sample_input_literal(item, expr_context)

    if scenario == "negative":
        if type_name in {"bool", "boolean"}:
            return "False"
        if metadata.get("array_subtype") or type_name == "array":
            return "[]"
        if "pointer" in type_name or "*" in str(item.get("type") or item.get("type_name") or "") or metadata.get("pointer_values"):
            return "None"
        if metadata.get("enum_values") or "enum" in type_name or "state" in type_name:
            return invalid_enum_literal(item)
        if "string" in type_name or metadata.get("string_length"):
            return repr("")
        if "float" in type_name or "double" in type_name:
            return "-1.0"
        if any(token in type_name for token in ["int8_t", "uint8_t", "int16_t", "uint16_t", "int32_t", "uint32_t", "int64_t", "uint64_t", "int", "integer"]):
            min_value = metadata.get("min_value")
            if isinstance(min_value, int):
                if min_value > 0:
                    return str(min_value - 1)
                return str(min_value - 1)
            return "-1"
        return "None"

    return sample_input_literal(item, expr_context)


def output_expectation_for_scenario(
    item: Dict[str, Any],
    expression: Dict[str, str],
    scenario: str,
) -> Tuple[str, str | None]:
    if scenario in {"positive", "boundary"}:
        return expected_output_value(item, expression)

    type_name = normalized_type(item)
    metadata = type_metadata(item)

    if "pointer" in type_name or "*" in str(item.get("type") or item.get("type_name") or ""):
        return "None", "=="
    if type_name in {"bool", "boolean"}:
        return "False", None
    if metadata.get("enum_values") or "enum" in type_name or "state" in type_name:
        return invalid_enum_literal(item), None
    if "string" in type_name or metadata.get("string_length"):
        return repr(""), "!="
    if "float" in type_name or "double" in type_name:
        return "-1.0", "!="
    if any(token in type_name for token in ["int8_t", "uint8_t", "int16_t", "uint16_t", "int32_t", "uint32_t", "int64_t", "uint64_t", "int", "integer"]):
        return "0", "!="
    return "None", "!="


def scenario_label(scenario: str) -> str:
    return {
        "positive": "Positive",
        "negative": "Negative",
        "boundary": "Boundary",
    }.get(scenario, scenario.title())


def boundary_summary(item: Dict[str, Any]) -> str:
    metadata = type_metadata(item)
    type_name = normalized_type(item)
    parts: List[str] = []
    if metadata.get("min_value") is not None and metadata.get("max_value") is not None:
        parts.append(f"Min value = {metadata.get('min_value')}")
        parts.append(f"Max value = {metadata.get('max_value')}")
    if metadata.get("values"):
        parts.append(f"Values = {metadata.get('values')}")
    if metadata.get("enum_values"):
        parts.append(f"Enum values = {metadata.get('enum_values')}")
    if metadata.get("pointer_values"):
        parts.append(f"Pointer values = {metadata.get('pointer_values')}")
    if metadata.get("array_subtype"):
        parts.append(f"Array subtype = {metadata.get('array_subtype_kind') or metadata.get('array_subtype')}")
    if metadata.get("array_length"):
        parts.append(f"Array length = {metadata.get('array_length')}")
    if metadata.get("array_formal"):
        parts.append(f"Array formal = {metadata.get('array_formal')}")
    if metadata.get("timing_intervals"):
        parts.append(f"Timing intervals = {metadata.get('timing_intervals')}")
    if metadata.get("trigger"):
        parts.append(f"Trigger = {metadata.get('trigger')}")
    if metadata.get("string_length"):
        parts.append(f"String length = {metadata.get('string_length')}")
    if metadata.get("valid_range"):
        parts.append(f"Valid string range = {metadata.get('valid_range')}")
    if not parts:
        parts.append(f"Type = {type_name}")
    return "; ".join(parts)


def scenario_case_comment(item: Dict[str, Any], scenario: str, value: str) -> List[str]:
    label = framework_label(item)
    lines = [f"    # {scenario_label(scenario)} Case:", f"    # - {label} = {value}"]
    if scenario == "boundary":
        lines.append(f"    # - Boundary conditions: {boundary_summary(item)}")
    elif scenario == "negative":
        lines.append(f"    # - Invalid input handling for {label}.")
    else:
        lines.append(f"    # - Expected behavior for valid input.")
    return lines


def high_boundary_literal(item: Dict[str, Any], requirement_name: str) -> str:
    type_name = normalized_type(item)
    metadata = type_metadata(item)

    if type_name in {"bool", "boolean"}:
        return "True"
    if metadata.get("array_subtype") or type_name == "array":
        return sample_array_literal(item, requirement_name)
    if "pointer" in type_name or "*" in str(item.get("type") or item.get("type_name") or "") or metadata.get("pointer_values"):
        return "object()"
    if metadata.get("enum_values") or "enum" in type_name or "state" in type_name:
        values = parse_semicolon_values(str(metadata.get("enum_values") or ""))
        return repr(values[-1]) if values else repr("VALUE")
    if "string" in type_name or metadata.get("string_length"):
        length = metadata.get("string_length")
        if isinstance(length, int) and length > 0:
            return repr("A" * min(length, 8))
        return repr("A")
    if "float" in type_name or "double" in type_name:
        max_value = metadata.get("max_value")
        if isinstance(max_value, (int, float)):
            return str(max_value)
        return "1.0"
    if any(token in type_name for token in ["int8_t", "uint8_t", "int16_t", "uint16_t", "int32_t", "uint32_t", "int64_t", "uint64_t", "int", "integer"]):
        max_value = metadata.get("max_value")
        if isinstance(max_value, int):
            return str(max_value)
        return sample_input_literal(item, requirement_name)
    return sample_input_literal(item, requirement_name)


def low_invalid_literal(item: Dict[str, Any], requirement_name: str) -> str:
    type_name = normalized_type(item)
    metadata = type_metadata(item)

    if type_name in {"bool", "boolean"}:
        return "False"
    if metadata.get("array_subtype") or type_name == "array":
        return "[]"
    if "pointer" in type_name or "*" in str(item.get("type") or item.get("type_name") or "") or metadata.get("pointer_values"):
        return "None"
    if metadata.get("enum_values") or "enum" in type_name or "state" in type_name:
        return invalid_enum_literal(item)
    if "string" in type_name or metadata.get("string_length"):
        return repr("")
    if "float" in type_name or "double" in type_name:
        min_value = metadata.get("min_value")
        if isinstance(min_value, (int, float)):
            return str(min_value - 1 if min_value > 0 else min_value)
        return "-1.0"
    if any(token in type_name for token in ["int8_t", "uint8_t", "int16_t", "uint16_t", "int32_t", "uint32_t", "int64_t", "uint64_t", "int", "integer"]):
        if "uint" in type_name:
            return "-1"
        min_value = metadata.get("min_value")
        if isinstance(min_value, int):
            return str(min_value - 1)
        return "-1"
    return "None"


def numeric_case_plan(item: Dict[str, Any], requirement_name: str) -> List[Dict[str, Any]]:
    type_name = normalized_type(item)
    metadata = type_metadata(item)
    min_value = metadata.get("min_value")
    max_value = metadata.get("max_value")
    label = framework_label(item)
    key = normalize_key(label)
    cases: List[Dict[str, Any]] = []

    def add_case_value(
        scenario: str,
        value: str,
        success: bool,
        coverage_lines: List[str],
        verify_states: bool = True,
    ) -> None:
        cases.append(
            {
                "scenario": scenario,
                "focus_label": label,
                "set_values": {key: value},
                "success": success,
                "coverage_lines": coverage_lines,
                "verify_states": verify_states,
            }
        )

    if type_name in {"bool", "boolean"}:
        return cases

    nominal = sample_input_literal(item, requirement_name)
    if not nominal or nominal in {"None", "object()"}:
        nominal = "1"

    if "float" in type_name or "double" in type_name:
        if min_value is not None and str(min_value) not in ("", "None"):
            nominal = "1.0" if str(min_value) == "0" else str(min_value if isinstance(min_value, (int, float)) else min_value)
    elif any(token in type_name for token in ["int8_t", "uint8_t", "int16_t", "uint16_t", "int32_t", "uint32_t", "int64_t", "uint64_t", "int", "integer"]):
        if isinstance(min_value, int) and isinstance(max_value, int):
            if 1 >= min_value and 1 <= max_value:
                nominal = "1"
            elif 0 >= min_value and 0 <= max_value:
                nominal = "0"
            else:
                nominal = str(min_value)

    add_case_value("positive", nominal, True, [f"{label} = {nominal}", "Positive case, expected behavior."])

    zero_value = "0"
    if zero_value != nominal:
        zero_success = True
        if isinstance(min_value, int) and zero_value == str(min_value):
            zero_success = True
        elif isinstance(min_value, int) and isinstance(max_value, int):
            zero_success = min_value <= 0 <= max_value
        add_case_value(
            "boundary",
            zero_value,
            zero_success,
            [f"{label} = 0", "Boundary condition at zero."],
            verify_states=zero_success,
        )

    if isinstance(min_value, int):
        min_literal = str(min_value)
        if min_literal != nominal and min_literal != zero_value:
            add_case_value(
                "boundary",
                min_literal,
                True,
                [f"{label} = {min_literal}", "Minimum valid boundary."],
            )

    if isinstance(max_value, int):
        max_literal = str(max_value)
        if max_literal != nominal and max_literal != zero_value:
            add_case_value(
                "boundary",
                max_literal,
                True,
                [f"{label} = {max_literal}", "Maximum valid boundary."],
            )

    low_invalid = low_invalid_literal(item, requirement_name)
    if low_invalid not in {nominal, zero_value, str(min_value), str(max_value)}:
        add_case_value(
            "negative",
            low_invalid,
            False,
            [f"{label} = {low_invalid}", "Invalid lower-bound or out-of-range value (min - 1)."],
            verify_states=False,
        )

    if isinstance(max_value, int):
        high_invalid = str(max_value + 1)
        if high_invalid not in {nominal, zero_value, str(min_value), str(max_value), low_invalid}:
            add_case_value(
                "negative",
                high_invalid,
                False,
                [f"{label} = {high_invalid}", "Invalid upper-bound or out-of-range value."],
                verify_states=False,
            )

    return cases


def case_comment_lines(title: str, coverage_lines: List[str]) -> List[str]:
    lines = [f"    # {title}"]
    for coverage in coverage_lines:
        lines.append(f"    # - {coverage}")
    return lines


def derive_component_name(requirement_id: str, payload: Dict[str, Any], override: str = "") -> str:
    explicit = str(override or payload.get("component_name") or payload.get("utility_name") or "").strip()
    if explicit:
        return explicit

    parts = [part for part in re.split(r"[-_]+", requirement_id or "") if part]
    if len(parts) >= 3:
        middle = parts[1]
        if any(char.isalpha() for char in middle):
            return middle

    for part in parts:
        if any(char.isalpha() for char in part):
            return part

    requirement_name = str(payload.get("requirement_name") or "").strip()
    if requirement_name:
        words = [word for word in re.split(r"\s+", requirement_name) if word]
        for word in words:
            if word.lower() not in {"create", "initialize", "initialization", "set", "get", "read", "write", "clear", "update", "check", "return"}:
                return sanitize_identifier(word)

    return "UTILITY"


def case_name(index: int) -> str:
    return f"test_TC{index:03d}"


def testcase_name(item: Dict[str, Any], index: int) -> str:
    focus = item.get("verification_identifier") or item.get("data_dictionary_term") or item.get("name") or "input"
    focus_slug = sanitize_identifier(str(focus))[:40]
    return f"test_TC{index:03d}_{focus_slug}"


def find_matching_output(expression: Dict[str, str], outputs: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    output_label = normalize_key(expression.get("output") or "")
    if not output_label:
        return None
    for item in outputs:
        label = normalize_key(framework_label(item))
        data_key = normalize_key(item.get("data_dictionary_term") or "")
        full_name = normalize_key(item.get("name") or "")
        if output_label == label or output_label == data_key or output_label in label or label in output_label:
            return item
        if output_label == full_name or output_label in full_name or full_name in output_label:
            return item
    return None


def generate_test_file(payload: Dict[str, Any], component_override: str = "") -> str:
    requirement_id = payload.get("requirement_id") or "REQUIREMENT"
    requirement_name = payload.get("requirement_name") or requirement_id
    component_name = derive_component_name(requirement_id, payload, component_override)
    resolved_items = payload.get("resolved_items") or []
    expressions = payload.get("expressions") or []

    inputs = [item for item in resolved_items if item.get("role") == "input"]
    outputs = [item for item in resolved_items if item.get("role") == "output"]
    states = [item for item in resolved_items if item.get("role") == "state"]
    main_expression = expressions[0] if expressions else {}

    def key_for(item: Dict[str, Any]) -> str:
        return normalize_key(framework_label(item))

    def build_valid_map(prefer_high: bool = False) -> Dict[str, str]:
        values: Dict[str, str] = {}
        for item in inputs:
            values[key_for(item)] = high_boundary_literal(item, requirement_name) if prefer_high else sample_input_literal(item, requirement_name)
        return values

    def add_case(
        cases: List[Dict[str, Any]],
        scenario: str,
        focus_label: str,
        set_values: Dict[str, str],
        success: bool,
        coverage_lines: List[str],
        verify_states: bool = True,
    ) -> None:
        cases.append(
            {
                "scenario": scenario,
                "focus_label": focus_label,
                "set_values": set_values,
                "success": success,
                "coverage_lines": coverage_lines,
                "verify_states": verify_states,
            }
        )

    cases: List[Dict[str, Any]] = []
    bool_items = [item for item in inputs if normalized_type(item) in {"bool", "boolean"}]
    pointer_items = [item for item in inputs if "pointer" in normalized_type(item) or "*" in str(item.get("type") or item.get("type_name") or "") or "reference" in key_for(item)]
    numeric_items = [
        item
        for item in inputs
        if item not in bool_items
        and item not in pointer_items
        and (any(token in normalized_type(item) for token in ["int", "integer", "uint", "float", "double"]) or type_metadata(item).get("min_value") is not None)
    ]

    for item in bool_items:
        label = framework_label(item)
        pos_values = build_valid_map()
        pos_values[key_for(item)] = "True"
        add_case(cases, "positive", label, pos_values, True, [f"{label} = True", "Positive case, expected behavior."])

        neg_values = build_valid_map()
        neg_values[key_for(item)] = "False"
        add_case(cases, "negative", label, neg_values, False, [f"{label} = False", "Negative case, invalid input handling."], verify_states=False)

    for item in numeric_items:
        for plan in numeric_case_plan(item, requirement_name):
            set_values = build_valid_map()
            set_values.update(plan["set_values"])
            add_case(
                cases,
                plan["scenario"],
                plan["focus_label"],
                set_values,
                plan["success"],
                plan["coverage_lines"],
                verify_states=plan["verify_states"],
            )

    for item in pointer_items:
        label = framework_label(item)
        pos_values = build_valid_map()
        pos_values[key_for(item)] = "object()"
        add_case(cases, "positive", label, pos_values, True, [f"{label} = not NULL", "Positive case, valid reference."])

        neg_values = build_valid_map()
        neg_values[key_for(item)] = "None"
        add_case(cases, "negative", label, neg_values, False, [f"{label} = NULL", "Negative case, invalid reference."], verify_states=False)

    if len(inputs) > 1:
        rbtca_values = build_valid_map(prefer_high=False)
        for item in bool_items:
            rbtca_values[key_for(item)] = "True"
        for item in pointer_items:
            rbtca_values[key_for(item)] = "object()"
        add_case(cases, "rbtca", "Additional RBTCA coverage", rbtca_values, True, ["All inputs valid with a stronger boundary mix.", "Additional RBTCA coverage."])

    deduped_cases: List[Dict[str, Any]] = []
    seen_signatures: set[Tuple[str, Tuple[Tuple[str, str], ...]]] = set()
    for case in cases:
        signature = (case["scenario"], tuple(sorted(case["set_values"].items())))
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        deduped_cases.append(case)
    cases = deduped_cases

    lines: List[str] = [
        f"# Item ID: {requirement_id}",
        "",
        "import pytest",
        "import pytest_smart as smart",
        "",
        "",
        "@pytest.fixture(autouse=True)",
        "def setUp(FW: smart.FW):",
        f'    FW.Set_Component("{component_name}")',
        "    FW.Reset()",
        "",
    ]

    for index, case in enumerate(cases, start=1):
        lines.append("")
        lines.append("# Purpose:")
        lines.append(f"# Verify the {requirement_name} utility shall:")
        lines.append("#")
        lines.append(f"# {requirement_id}:")
        lines.append(f"# - {case['focus_label']}")
        lines.append("#")
        lines.append("# Conditions Verified:")
        for coverage_line in case["coverage_lines"]:
            lines.append(f"# - {coverage_line}")
        lines.append("#")
        lines.append("# Coverage Objectives:")
        lines.append(f"# - {scenario_label(case['scenario'])} case.")
        lines.append(f"# - Verify {requirement_id}.")
        lines.append("")
        lines.append(f"def {case_name(index)}(FW: smart.FW):")
        lines.append(f"    FW.Id({index})")
        lines.append("")

        for item in inputs:
            label = framework_label(item)
            value = case["set_values"].get(key_for(item), sample_input_literal(item, requirement_name))
            lines.append(f'    FW.Set("{label}", {value})')

        lines.append("")
        lines.append("    FW.Run()")
        lines.append("")

        for item in outputs:
            label = framework_label(item)
            if case["success"]:
                value, comparison = expected_output_value(item, main_expression)
            else:
                value, comparison = output_expectation_for_scenario(item, main_expression, "negative")
            if comparison:
                lines.append(f'    FW.Verify("{label}", {value}, comparison={comparison!r})')
            else:
                lines.append(f'    FW.Verify("{label}", {value})')

        if case["success"] and case["verify_states"]:
            for item in states:
                label = state_framework_label(item)
                state_value, comparison = derive_state_expected_value(item, case["set_values"])
                if comparison:
                    lines.append(f'    FW.Verify("{label}", {state_value}, comparison={comparison!r})')
                else:
                    lines.append(f'    FW.Verify("{label}", {state_value})')

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def json_input_files(input_dir: Path) -> List[Path]:
    return sorted([path for path in input_dir.rglob("*.json") if path.is_file()])


def generate_from_json_file(input_path: Path, output_dir: Path, component_override: str = "") -> Path:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    requirement_id = payload.get("requirement_id") or input_path.stem
    output_name = f"test_{sanitize_identifier(requirement_id)}.py"
    output_path = output_dir / output_name
    output_path.write_text(generate_test_file(payload, component_override=component_override), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate python testcases from extractor JSON")
    parser.add_argument("--input", "-i", help="Path to extractor JSON output")
    parser.add_argument("--input-dir", help="Generate testcase files for every JSON file in this directory")
    parser.add_argument(
        "--output-dir",
        "-o",
        default=str(Path.home() / "Downloads"),
        help="Directory to write the generated python file",
    )
    parser.add_argument("--output-name", help="Optional output filename override")
    parser.add_argument("--component-name", help="Override the component name used in FW.Set_Component")
    parser.add_argument("--workers", type=int, default=max(1, min(8, (os.cpu_count() or 1))), help="Worker count for batch generation")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.input_dir:
        input_dir = Path(args.input_dir).expanduser().resolve()
        json_files = json_input_files(input_dir)
        if not json_files:
            print(f"No JSON files found in: {input_dir}")
            return

        def process_file(input_path: Path) -> Path:
            return generate_from_json_file(input_path, output_dir, component_override=args.component_name or "")

        if args.workers > 1 and len(json_files) > 1:
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                outputs = list(executor.map(process_file, json_files))
        else:
            outputs = [process_file(input_path) for input_path in json_files]

        print(f"Generated {len(outputs)} test files in: {output_dir}")
        return

    if not args.input:
        parser.error("either --input/-i or --input-dir must be provided")

    input_path = Path(args.input).expanduser().resolve()
    payload = json.loads(input_path.read_text(encoding="utf-8"))

    requirement_id = payload.get("requirement_id") or input_path.stem
    default_name = f"test_{sanitize_identifier(requirement_id)}.py"
    output_name = args.output_name or default_name
    output_path = output_dir / output_name

    output_path.write_text(generate_test_file(payload, component_override=args.component_name or ""), encoding="utf-8")
    print(f"Generated test file: {output_path}")


if __name__ == "__main__":
    main()
