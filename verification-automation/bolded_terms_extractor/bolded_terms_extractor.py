#!/usr/bin/env python3
"""
Bolded Terms Extractor Agent

Extracts bolded markdown terms from requirement files and optionally resolves
their types using the data dictionary files in this repository.

Usage:
  python bolded_terms_extractor.py --file requirements/LLR/FAF-LLR-490.md
  python bolded_terms_extractor.py --all
  python bolded_terms_extractor.py --llr --resolve-types
"""

from __future__ import annotations

import argparse
import csv
import os
import json
import re
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Optional, Tuple


@dataclass
class BoldedTerm:
    term: str
    file_path: str
    line_number: int
    requirement_id: str = ""
    input_type: Optional[str] = None
    verification_id: Optional[str] = None
    verification_files: List[str] = field(default_factory=list)
    context_func_name: str = ""
    type_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RequirementTerms:
    requirement_id: str
    file_path: str
    bolded_terms: List[BoldedTerm] = field(default_factory=list)

    @property
    def term_strings(self) -> List[str]:
        return [t.term for t in self.bolded_terms]


@dataclass
class DataDictionaryEntry:
    func_name: str
    param_name: str
    param_type: str
    param_mode: str
    ped: str
    producer: str


@dataclass
class StructMemberEntry:
    struct_name: str
    member_name: str
    member_type: str
    ped: str
    producer: str


@dataclass
class HeaderFunctionSpec:
    attention: str
    c_function: str
    return_type: str
    param_names: List[str] = field(default_factory=list)
    header_path: str = ""


@dataclass
class ResolvedIOItem:
    role: str
    name: str
    data_dictionary_term: str
    type_name: str
    verification_identifier: str = ""
    type_metadata: Dict[str, Any] = field(default_factory=dict)
    requirement_id: str = ""
    source_function: str = ""


@dataclass
class CodeAccessEntry:
    source_name: str
    target_path: str
    function_name: str
    root_name: str = ""


def extract_requirement_id(content: str) -> str:
    match = re.search(r"### Item ID\s*\n\s*([A-Z0-9\-]+)", content)
    return match.group(1) if match else ""


def extract_requirement_name(content: str) -> str:
    match = re.search(r"### Name\s*\n\s*([^\n]+)", content)
    return match.group(1).strip() if match else ""


def extract_bolded_terms(file_path: Path) -> RequirementTerms:
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        print(f"Warning: Could not read {file_path}: {exc}")
        return RequirementTerms(requirement_id="", file_path=str(file_path))

    requirement_id = extract_requirement_id(content)
    requirement_name = extract_requirement_name(content)
    bold_pattern = re.compile(r"\*\*([^*]+?)\*\*")
    terms: List[BoldedTerm] = []

    for line_num, line in enumerate(content.splitlines(), start=1):
        for match in bold_pattern.findall(line):
            cleaned = match.strip().rstrip(",;:").strip()
            if not cleaned or cleaned.startswith("#"):
                continue
            terms.append(
                BoldedTerm(
                    term=cleaned,
                    file_path=str(file_path),
                    line_number=line_num,
                    requirement_id=requirement_id,
                    context_func_name=requirement_name,
                )
            )

    return RequirementTerms(
        requirement_id=requirement_id,
        file_path=str(file_path),
        bolded_terms=terms,
    )


def find_requirement_files(base_path: Path, requirement_type: str = "all") -> List[Path]:
    files: List[Path] = []
    if requirement_type in ("all", "llr"):
        llr_path = base_path / "requirements" / "LLR"
        if llr_path.exists():
            files.extend(sorted(llr_path.rglob("*.md")))
    if requirement_type in ("all", "hlr"):
        hlr_path = base_path / "requirements" / "HLR"
        if hlr_path.exists():
            files.extend(sorted(hlr_path.rglob("*.md")))
    return files


def find_requirement_by_id(base_path: Path, requirement_id: str) -> Optional[Path]:
    pattern = re.compile(r"### Item ID\s*\n\s*" + re.escape(requirement_id))
    for md_file in find_requirement_files(base_path, "all"):
        try:
            if pattern.search(md_file.read_text(encoding="utf-8")):
                return md_file
        except Exception:
            continue
    return None


def _data_dictionary_dir(base_path: Path) -> Path:
    primary = base_path / "requirements" / "data_dictionaries"
    legacy = base_path / "requirements" / "data_dictionary"
    return primary if primary.exists() else legacy


def normalize_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def sanitize_identifier(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", text or "").strip("_")
    return cleaned or "generated"


def normalize_struct_member_key(text: str) -> str:
    return normalize_key(text)


def struct_member_to_code_name(member_name: str) -> str:
    normalized = normalize_key(member_name)
    aliases = {
        "allocated memory buffer": "allocatedMemoryBuffer",
        "element size": "elementSize",
        "capacity": "capacity",
        "number of elements in the queue": "count",
        "front element": "head",
        "end of queue": "tail",
        "mutex": "mutex",
        "mutex counter": "mutexCounter",
        "maximum number of elements that the queue is capable of holding": "capacity",
    }
    if normalized in aliases:
        return aliases[normalized]

    parts = normalized.split()
    if not parts:
        return member_name.strip()
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def extract_c_function_block(content: str, function_name: str) -> Optional[Tuple[str, str, str]]:
    """
    Return the matched function signature and body for a C function name.
    The tuple contains (full_match, params_text, body_text).
    """
    pattern = re.compile(rf"([A-Za-z_][A-Za-z0-9_\s\*]+?)\b{re.escape(function_name)}\s*\((.*?)\)\s*\{{", re.S)
    match = pattern.search(content)
    if not match:
        return None

    start = match.end() - 1
    depth = 0
    for idx in range(start, len(content)):
        char = content[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return match.group(0), match.group(2), content[start + 1 : idx]

    return None


def infer_root_name_from_body(body: str, preferred_root_name: str = "") -> str:
    if preferred_root_name:
        return preferred_root_name

    declaration_match = re.search(
        r"\b[A-Za-z_][A-Za-z0-9_]*\s*\*\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*NULL\s*;",
        body,
    )
    if declaration_match:
        return declaration_match.group(1).strip()

    access_match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:->|\[0\]\.)\s*[A-Za-z_][A-Za-z0-9_]*\s*=", body)
    if access_match:
        return access_match.group(1).strip()

    return ""


def infer_utility_key(function_name: str, func_lookup: Dict[str, List[DataDictionaryEntry]]) -> str:
    entries = func_lookup.get(function_name, [])
    producers = [entry.producer.strip() for entry in entries if entry.producer.strip()]
    if producers:
        return max(set(producers), key=producers.count)
    return ""


def clean_requirement_title(title: str) -> str:
    cleaned = (title or "").strip()
    cleaned = re.sub(r"\s*-\s*return\s*$", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


def infer_requirement_function_name(requirement_title: str, bold_terms: List[BoldedTerm], func_lookup: Dict[str, List[DataDictionaryEntry]]) -> str:
    requirement_key = normalize_key(requirement_title)
    bold_keys = {normalize_key(term.term) for term in bold_terms}

    for func_name in func_lookup.keys():
        func_key = normalize_key(func_name)
        if func_key in bold_keys:
            return func_name

    for func_name in func_lookup.keys():
        func_key = normalize_key(func_name)
        if func_key == requirement_key:
            return func_name

    best_name = ""
    best_score = 0
    for func_name in func_lookup.keys():
        func_key = normalize_key(func_name)
        score = 0
        if func_key in bold_keys:
            score += 10
        if func_key == requirement_key:
            score += 10
        if func_key and func_key in requirement_key:
            score += 2
        if requirement_key and requirement_key in func_key:
            score += 2
        for bold_key in bold_keys:
            if func_key and (func_key in bold_key or bold_key in func_key):
                score += 1
        score += min(len(func_key.split()), 5)
        if score > best_score:
            best_name = func_name
            best_score = score

    return best_name


def parse_header_param_name(param_text: str) -> Optional[str]:
    param_text = param_text.strip()
    if not param_text or param_text.lower() == "void":
        return None
    pieces = re.split(r"\s+", param_text)
    if not pieces:
        return None
    candidate = pieces[-1].strip()
    candidate = candidate.lstrip("*").rstrip("[]")
    return candidate or None


def load_header_function_specs(base_path: Path) -> Dict[str, HeaderFunctionSpec]:
    specs: Dict[str, HeaderFunctionSpec] = {}
    source_root = base_path / "software" / "source"
    if not source_root.exists():
        return specs

    for h_file in sorted(source_root.rglob("*.h")):
        try:
            content = h_file.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"Warning: Could not read {h_file}: {exc}")
            continue

        fn_matches = list(re.finditer(r"@fn\s+([A-Za-z_][A-Za-z0-9_]*)", content))
        for idx, fn_match in enumerate(fn_matches):
            c_function = fn_match.group(1).strip()
            next_start = fn_matches[idx + 1].start() if idx + 1 < len(fn_matches) else len(content)
            after = content[fn_match.end():next_start]

            block_start = content.rfind("/**", 0, fn_match.start())
            block_end = content.find("*/", fn_match.start())
            block = content[block_start:block_end] if block_start != -1 and block_end != -1 else ""
            attention_match = re.search(r"@attention\s+([^\n*]+)", block)
            attention = attention_match.group(1).strip() if attention_match else ""

            proto_line = ""
            for line in after.splitlines():
                stripped = line.strip()
                if c_function in stripped and "(" in stripped and stripped.endswith(";"):
                    proto_line = stripped
                    break
            if not proto_line:
                continue

            proto_head, proto_tail = proto_line.split("(", 1)
            return_type = proto_head.rsplit(c_function, 1)[0].strip()
            params_text = proto_tail.rsplit(")", 1)[0].strip()
            param_names: List[str] = []
            if params_text and params_text.lower() != "void":
                for raw_param in params_text.split(","):
                    parsed = parse_header_param_name(raw_param)
                    if parsed:
                        param_names.append(parsed)

            spec = HeaderFunctionSpec(
                attention=attention,
                c_function=c_function,
                return_type=return_type,
                param_names=param_names,
                header_path=str(h_file),
            )

            for key in {
                normalize_key(spec.attention),
                normalize_key(spec.c_function),
            }:
                if key:
                    specs[key] = spec

    return specs


def load_data_dictionary(
    base_path: Path,
) -> Tuple[Dict[str, DataDictionaryEntry], Dict[str, List[DataDictionaryEntry]]]:
    param_lookup: Dict[str, DataDictionaryEntry] = {}
    func_lookup: DefaultDict[str, List[DataDictionaryEntry]] = defaultdict(list)
    data_dict_path = _data_dictionary_dir(base_path)

    if not data_dict_path.exists():
        print(f"Warning: Data dictionary path not found: {data_dict_path}")
        return param_lookup, func_lookup

    for csv_file in sorted(data_dict_path.glob("*.csv")):
        try:
            with csv_file.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                fields = set(reader.fieldnames or [])
                for row in reader:
                    func_name = ""
                    param_name = ""
                    param_type = ""
                    param_mode = row.get("PARAM_MODE", "") or row.get("MODE", "")
                    ped = row.get("PED", "")
                    producer = row.get("PRODUCER", "")

                    if "FUNC_NAME" in fields:
                        func_name = row.get("FUNC_NAME", "")
                        param_name = row.get("PARAM_NAME", "")
                        param_type = row.get("PARAM_TYPE", "")
                    elif "DATA_ENUM_NAME" in fields:
                        func_name = row.get("DATA_ENUM_NAME", "")
                        param_name = row.get("DATA_ENUM_VALUE_NAME", "")
                        param_type = row.get("TYPE", "")
                    elif "ENUM_NAME" in fields:
                        func_name = row.get("ENUM_NAME", "")
                        param_name = row.get("ENUM_VALUE_NAME", "")
                        param_type = row.get("ENUM_NAME", "")
                    elif "DATA_NUM_NAME" in fields:
                        func_name = row.get("DATA_NUM_NAME", "")
                        param_name = row.get("DATA_NUM_NAME", "")
                        param_type = row.get("TYPE", "")
                    elif "DATA_STRUCT_NAME" in fields:
                        func_name = row.get("DATA_STRUCT_NAME", "")
                        param_name = row.get("DATA_MEMBER_NAME", "")
                        param_type = row.get("DATA_MEMBER_TYPE", "")
                    elif "STRUCT_NAME" in fields:
                        func_name = row.get("STRUCT_NAME", "")
                        param_name = row.get("MEMBER_NAME", "")
                        param_type = row.get("MEMBER_TYPE", "")
                    elif "DATA_TYPE_NAME" in fields:
                        func_name = row.get("DATA_TYPE_NAME", "")
                        param_name = row.get("DATA_TYPE_NAME", "")
                        param_type = row.get("SIZE", "")
                    elif "IDD_NAME" in fields:
                        func_name = row.get("IDD_NAME", "")
                        param_name = row.get("IDD_MEMBER_NAME", "")
                        param_type = row.get("IDD_MEMBER_TYPE", "")
                    else:
                        continue

                    entry = DataDictionaryEntry(
                        func_name=func_name.strip(),
                        param_name=param_name.strip(),
                        param_type=param_type.strip(),
                        param_mode=param_mode.strip(),
                        ped=ped.strip(),
                        producer=producer.strip(),
                    )
                    if entry.param_name:
                        param_lookup[entry.param_name] = entry
                    if entry.func_name:
                        func_lookup[entry.func_name].append(entry)
        except Exception as exc:
            print(f"Warning: Could not read {csv_file}: {exc}")

    return param_lookup, func_lookup


def load_enum_lookup(base_path: Path) -> Dict[str, List[str]]:
    enum_lookup: DefaultDict[str, List[str]] = defaultdict(list)
    path = _data_dictionary_dir(base_path) / "types_enum.csv"
    if not path.exists():
        return dict(enum_lookup)
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                enum_name = row.get("ENUM_NAME", "")
                enum_value = row.get("ENUM_VALUE_NAME", "")
                if enum_name and enum_value:
                    enum_lookup[enum_name].append(enum_value)
    except Exception as exc:
        print(f"Warning: Could not read {path}: {exc}")
    return dict(enum_lookup)


def load_number_lookup(base_path: Path) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    data_dir = _data_dictionary_dir(base_path)
    candidates = [data_dir / "type_numbers.csv", data_dir / "types_number.csv", data_dir / "data_number.csv"]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        return lookup
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (
                    row.get("NUM_NAME", "")
                    or row.get("DATA_NUM_NAME", "")
                    or row.get("DATA_TYPE_NAME", "")
                    or row.get("NUM_TYPE", "")
                    or row.get("TYPE", "")
                )
                if key:
                    lookup[key] = {
                        "min": row.get("MIN", ""),
                        "max": row.get("MAX", ""),
                        "units": row.get("UNITS", ""),
                        "ped": row.get("PED", ""),
                    }
    except Exception as exc:
        print(f"Warning: Could not read {path}: {exc}")
    return lookup


def load_array_lookup(base_path: Path) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    path = _data_dictionary_dir(base_path) / "types_array.csv"
    if not path.exists():
        return lookup
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = row.get("ARRAY_NAME", "")
                if key:
                    lookup[key] = {
                        "dims": row.get("ARRAY_DIMS", ""),
                        "type": row.get("ARRAY_TYPE", ""),
                        "ped": row.get("PED", ""),
                    }
    except Exception as exc:
        print(f"Warning: Could not read {path}: {exc}")
    return lookup


def load_array_constants(base_path: Path) -> Dict[str, List[Dict[str, Any]]]:
    lookup: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    path = _data_dictionary_dir(base_path) / "data_array.csv"
    if not path.exists():
        return dict(lookup)
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = row.get("DATA_ARRAY_NAME", "")
                if key:
                    lookup[key].append(
                        {
                            "index": row.get("ARRAY_INDEX", ""),
                            "value": row.get("ARRAY_INDEX_VALUE", ""),
                            "ped": row.get("PED", ""),
                        }
                    )
    except Exception as exc:
        print(f"Warning: Could not read {path}: {exc}")
    return dict(lookup)


def load_struct_lookup(base_path: Path) -> Dict[str, List[StructMemberEntry]]:
    lookup: DefaultDict[str, List[StructMemberEntry]] = defaultdict(list)
    data_dir = _data_dictionary_dir(base_path)
    candidates = [data_dir / "type_struct.csv", data_dir / "data_struct.csv"]
    for path in candidates:
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                fields = set(reader.fieldnames or [])
                for row in reader:
                    if "STRUCT_NAME" in fields:
                        struct_name = row.get("STRUCT_NAME", "")
                        member_name = row.get("STRUCT_VAR", "")
                        member_type = row.get("STRUCT_VAR_TYPE", "")
                    elif "DATA_STRUCT_NAME" in fields:
                        struct_name = row.get("DATA_STRUCT_NAME", "")
                        member_name = row.get("STRUCT_VAR", "")
                        member_type = row.get("TYPE", "")
                    else:
                        continue

                    if struct_name and member_name:
                        entry = StructMemberEntry(
                            struct_name=struct_name.strip(),
                            member_name=member_name.strip(),
                            member_type=member_type.strip(),
                            ped=(row.get("PED", "") or "").strip(),
                            producer=(row.get("PRODUCER", "") or "").strip(),
                        )
                        lookup[normalize_key(struct_name)].append(entry)
                        if entry.producer:
                            lookup[normalize_key(entry.producer)].append(entry)
        except Exception as exc:
            print(f"Warning: Could not read {path}: {exc}")
    return dict(lookup)


def load_code_accessors(base_path: Path, preferred_root_name: str = "") -> Dict[str, Dict[str, CodeAccessEntry]]:
    """
    Parse source files to map function inputs to internal utility paths.
    """
    accessors: Dict[str, Dict[str, CodeAccessEntry]] = {}
    source_root = base_path / "software" / "source"
    if not source_root.exists():
        return accessors

    for c_file in sorted(source_root.rglob("*.c")):
        try:
            content = c_file.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"Warning: Could not read {c_file}: {exc}")
            continue

        fn_matches = list(re.finditer(r"@fn\s+([A-Za-z_][A-Za-z0-9_]*)", content))
        for fn_match in fn_matches:
            function_name = fn_match.group(1).strip()
            function_block = extract_c_function_block(content, function_name)
            if not function_block:
                continue

            _, params_text, body = function_block
            if not function_name.lower().endswith("create"):
                continue

            param_names: List[str] = []
            for raw_param in params_text.split(","):
                parsed = parse_header_param_name(raw_param)
                if parsed:
                    param_names.append(parsed)

            source_root_name = infer_root_name_from_body(body)
            target_root_name = preferred_root_name or source_root_name
            if not target_root_name:
                continue

            assign_pattern = re.compile(
                r"\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:->|\[0\]\.)"
                r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*;"
            )
            for access_root, field_name, source_name in assign_pattern.findall(body):
                source_lower = source_name.strip()
                if source_lower not in param_names:
                    continue
                if source_root_name and access_root != source_root_name:
                    continue
                accessors.setdefault(function_name, {})[source_lower] = CodeAccessEntry(
                    source_name=source_lower,
                    target_path=f"{target_root_name}[0].{field_name}",
                    function_name=function_name,
                    root_name=target_root_name,
                )

    return accessors


def load_verification_data_dictionary(base_path: Path) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    candidates = [
        base_path / "verification" / "verification_data_dic.csv",
        base_path / "verification" / "test-procedures" / "procedure-data" / "data_dictionary.csv",
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        return lookup
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                req_name = row.get("RequirementName", "") or row.get("requirement_name", "")
                verification_id = row.get("VerificationIdentifier", "") or row.get("verification_id", "")
                if req_name and verification_id:
                    lookup[req_name] = verification_id
    except Exception as exc:
        print(f"Warning: Could not read verification data dictionary: {exc}")
    return lookup


def find_verification_identifiers_in_code(base_path: Path) -> Dict[str, List[str]]:
    term_files: DefaultDict[str, List[str]] = defaultdict(list)
    verification_path = base_path / "verification" / "test-cases"
    if not verification_path.exists():
        return dict(term_files)

    set_pattern = re.compile(r"FW\.(?:Set|Verify)\s*\(\s*['\"]([^'\"]+)['\"]")
    for py_file in verification_path.rglob("*.py"):
        try:
            content = py_file.read_text(encoding="utf-8")
            for match in set_pattern.findall(content):
                term_files[match.strip()].append(str(py_file))
        except Exception:
            continue
    return dict(term_files)


def resolve_term_types(
    terms: List[BoldedTerm],
    param_lookup: Dict[str, DataDictionaryEntry],
    func_lookup: Dict[str, List[DataDictionaryEntry]],
    requirement_id: str = "",
) -> List[BoldedTerm]:
    param_lookup_lower = {k.lower(): v for k, v in param_lookup.items()}
    func_lookup_lower = {k.lower(): v for k, v in func_lookup.items()}

    for term in terms:
        key = term.term.strip()
        lower = key.lower()

        entry = param_lookup.get(key) or param_lookup_lower.get(lower)
        if entry:
            term.input_type = entry.param_type
            continue

        entries = func_lookup.get(key) or func_lookup_lower.get(lower)
        if entries:
            for candidate in entries:
                if candidate.param_name.upper() != "NULL" and candidate.param_type:
                    term.input_type = candidate.param_type
                    break
            if not term.input_type and entries[0].param_type:
                term.input_type = entries[0].param_type
            continue

        if requirement_id:
            for func_entries in func_lookup.values():
                for candidate in func_entries:
                    if candidate.param_name.lower() == lower and candidate.param_type:
                        term.input_type = candidate.param_type
                        break
                if term.input_type:
                    break

    return terms


def resolve_verification_identifiers(
    terms: List[BoldedTerm],
    verification_lookup: Dict[str, str],
    term_to_files: Dict[str, List[str]],
    param_lookup: Dict[str, DataDictionaryEntry],
    func_lookup: Dict[str, List[DataDictionaryEntry]],
    requirement_id: str = "",
    c_header_params: Optional[Dict[str, Dict[str, str]]] = None,
) -> List[BoldedTerm]:
    c_header_params = c_header_params or {}
    for term in terms:
        full_term = f"{term.context_func_name}: {term.term}" if term.context_func_name else term.term
        if full_term in verification_lookup:
            term.verification_id = verification_lookup[full_term]
        elif term.term in verification_lookup:
            term.verification_id = verification_lookup[term.term]
        else:
            for key, value in verification_lookup.items():
                if key.lower().endswith(f": {term.term.lower()}"):
                    term.verification_id = value
                    break

        if not term.verification_id and requirement_id:
            for func_name, entries in func_lookup.items():
                for entry in entries:
                    if entry.param_name.lower() == term.term.lower():
                        if func_name in c_header_params and c_header_params[func_name]:
                            term.verification_id = next(iter(c_header_params[func_name].keys()))
                        else:
                            term.verification_id = entry.param_name
                        break
                if term.verification_id:
                    break

        for name, files in term_to_files.items():
            if name.lower() == term.term.lower() or name.lower().endswith(f": {term.term.lower()}"):
                term.verification_files = files
                break

    return terms


def compute_type_metadata(
    term: BoldedTerm,
    enum_lookup: Dict[str, List[str]],
    number_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
    array_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
    array_constants: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    input_type = term.input_type or ""
    lower = input_type.lower()
    number_lookup = number_lookup or {}
    array_lookup = array_lookup or {}
    array_constants = array_constants or {}

    def lookup_enum_values() -> Optional[List[str]]:
        candidates = [input_type, term.term, term.context_func_name]
        for candidate in candidates:
            candidate = (candidate or "").strip()
            if not candidate:
                continue
            exact = enum_lookup.get(candidate)
            if exact:
                return exact
            for enum_name, values in enum_lookup.items():
                enum_lower = enum_name.lower()
                cand_lower = candidate.lower()
                if enum_lower == cand_lower or enum_lower in cand_lower or cand_lower in enum_lower:
                    return values
        return None

    def parse_array_length() -> Optional[int]:
        if input_type in array_lookup:
            dims = array_lookup[input_type].get("dims", "")
            match = re.search(r"\[(\d+)\]", dims)
            if match:
                return int(match.group(1))
        return None

    def classify_array_subtype(subtype: str) -> str:
        subtype_lower = subtype.lower()
        if not subtype_lower:
            return "unknown"
        if subtype_lower in ("bool", "boolean"):
            return "boolean_const"
        if "char" in subtype_lower or "string" in subtype_lower:
            return "string_const"
        if "float" in subtype_lower or "double" in subtype_lower:
            return "float_const"
        if subtype_lower in enum_lookup or "enum" in subtype_lower or "state" in subtype_lower:
            return "enum_const"
        if any(token in subtype_lower for token in ("int", "uint", "short", "long", "size_t", "byte", "count")):
            return "integer_const"
        return "integer_const"

    if lower in ("bool", "boolean"):
        metadata["values"] = "True and False"

    if input_type in number_lookup:
        num = number_lookup[input_type]
        if num.get("min"):
            metadata["min_value"] = num["min"]
        if num.get("max"):
            metadata["max_value"] = num["max"]
        if num.get("units"):
            metadata["units"] = num["units"]

    normalized = lower.replace("_t", "")
    for name, info in number_lookup.items():
        if name.lower().replace("_t", "") == normalized:
            if "min_value" not in metadata and info.get("min"):
                metadata["min_value"] = info["min"]
            if "max_value" not in metadata and info.get("max"):
                metadata["max_value"] = info["max"]
            if "units" not in metadata and info.get("units"):
                metadata["units"] = info["units"]
            break

    int_types = {
        "int8_t": (-128, 127),
        "uint8_t": (0, 255),
        "int16_t": (-32768, 32767),
        "uint16_t": (0, 65535),
        "int32_t": (-2147483648, 2147483647),
        "uint32_t": (0, 4294967295),
        "int64_t": (-9223372036854775808, 9223372036854775807),
        "uint64_t": (0, 18446744073709551615),
    }
    if "min_value" not in metadata:
        if lower in int_types:
            metadata["min_value"], metadata["max_value"] = int_types[lower]
        elif lower.startswith("float32") or lower == "float":
            metadata["min_value"] = "FLT_MIN"
            metadata["max_value"] = "FLT_MAX"
        elif lower.startswith("float64") or "double" in lower or "float" in lower:
            metadata["min_value"] = "DBL_MIN"
            metadata["max_value"] = "DBL_MAX"
        elif "int" in lower or "integer" in lower:
            metadata["min_value"] = -2147483648
            metadata["max_value"] = 2147483647

    enum_values = lookup_enum_values()
    if enum_values:
        metadata["enum_values"] = "; ".join(enum_values)
    elif lower == "enum" or "enum" in lower or "state" in lower:
        metadata["enum_values"] = ""

    if "*" in input_type:
        metadata["pointer_values"] = "NULL; not NULL"

    if lower == "string" or ("char" in lower and "*" in input_type) or "string" in lower:
        metadata["string_length"] = "variable"
        metadata["valid_range"] = "implementation defined"

    if input_type in array_lookup:
        arr = array_lookup[input_type]
        subtype = arr.get("type", "")
        length = parse_array_length()
        metadata["array_subtype"] = subtype
        metadata["array_subtype_kind"] = classify_array_subtype(subtype)
        metadata["array_length"] = length if length is not None else arr.get("dims", "")
        metadata["array_dims"] = arr.get("dims", "")
        if length is not None:
            values = [item["value"] for item in array_constants.get(input_type, []) if item.get("value", "") != ""]
            if values:
                metadata["array_formal"] = "[" + ",".join(values) + "]"
            else:
                metadata["array_formal"] = "[" + ",".join(f"ele{i}" for i in range(1, min(length, 3) + 1)) + "]"
        if input_type in array_constants:
            metadata["array_values"] = [item["value"] for item in array_constants[input_type]]
            if "array_formal" not in metadata:
                metadata["array_formal"] = "[" + ",".join(metadata["array_values"]) + "]"

    if "timing" in lower or "interval" in lower or "cycle" in lower or "timer" in lower:
        metadata["timing_intervals"] = "seconds or milliseconds or cycles"
        metadata["trigger"] = "true"

    if "calculated" in lower or "calc" in lower:
        metadata["calculation"] = "intermediate variable formula using other input variables and math operations"

    return metadata


def build_resolved_io_items(
    requirement_terms: RequirementTerms,
    requirement_title: str,
    param_lookup: Dict[str, DataDictionaryEntry],
    func_lookup: Dict[str, List[DataDictionaryEntry]],
    struct_lookup: Dict[str, List[StructMemberEntry]],
    code_accessors: Dict[str, Dict[str, CodeAccessEntry]],
    enum_lookup: Dict[str, List[str]],
    number_lookup: Dict[str, Dict[str, Any]],
    array_lookup: Dict[str, Dict[str, Any]],
    array_constants: Dict[str, List[Dict[str, Any]]],
    header_specs: Dict[str, HeaderFunctionSpec],
    state_root_name: str = "",
) -> List[ResolvedIOItem]:
    requirement_title = clean_requirement_title(requirement_title)
    function_name = infer_requirement_function_name(requirement_title, requirement_terms.bolded_terms, func_lookup)
    if not function_name and requirement_title:
        function_name = requirement_title
    utility_key = infer_utility_key(function_name, func_lookup)
    utility_struct_members = struct_lookup.get(normalize_key(utility_key), [])

    entries = func_lookup.get(function_name, [])
    bold_lookup = {normalize_key(term.term): term for term in requirement_terms.bolded_terms}
    header_spec = header_specs.get(normalize_key(function_name)) or header_specs.get(normalize_key(requirement_title))
    header_param_iter = iter(header_spec.param_names) if header_spec else iter(())
    function_accessors = code_accessors.get(header_spec.c_function if header_spec else "", {})

    resolved_items: List[ResolvedIOItem] = []
    for entry in entries:
        if not entry.param_name or entry.param_name.upper() == "NULL":
            continue

        mode = (entry.param_mode or "").upper()
        if mode in ("OUT", "RETURN"):
            role = "output"
        else:
            role = "input"

        matched_bold = bold_lookup.get(normalize_key(entry.param_name))
        if not matched_bold:
            continue

        fake_term = BoldedTerm(
            term=entry.param_name,
            file_path=matched_bold.file_path,
            line_number=matched_bold.line_number,
            requirement_id=requirement_terms.requirement_id,
            input_type=entry.param_type,
            context_func_name=function_name,
        )
        metadata = compute_type_metadata(fake_term, enum_lookup, number_lookup, array_lookup, array_constants)

        verification_identifier = ""
        if role == "input" and header_spec:
            header_param_name = next(header_param_iter, "") or ""
            verification_identifier = header_param_name
            if header_param_name in function_accessors:
                verification_identifier = function_accessors[header_param_name].target_path
        elif role == "output" and mode == "RETURN":
            verification_identifier = "return"

        if not verification_identifier and matched_bold.verification_id:
            verification_identifier = matched_bold.verification_id

        resolved_items.append(
            ResolvedIOItem(
                role=role,
                name=f"{requirement_title}: {entry.param_name}" if requirement_title else entry.param_name,
                data_dictionary_term=entry.param_name,
                type_name=entry.param_type,
                verification_identifier=verification_identifier,
                type_metadata=metadata,
                requirement_id=requirement_terms.requirement_id,
                source_function=function_name,
            )
        )

    state_member_lookup: Dict[str, StructMemberEntry] = {}
    for member in utility_struct_members:
        state_member_lookup[normalize_struct_member_key(member.member_name)] = member
        state_member_lookup[normalize_struct_member_key(struct_member_to_code_name(member.member_name))] = member

    inferred_root_name = state_root_name
    if not inferred_root_name and function_accessors:
        inferred_root_name = next((entry.root_name for entry in function_accessors.values() if entry.root_name), "")
    if not inferred_root_name:
        inferred_root_name = normalize_key(utility_key).replace(" ", "") or "state"

    for term in requirement_terms.bolded_terms:
        raw_term = term.term.strip()
        if ":" not in raw_term:
            continue
        suffix = raw_term.split(":", 1)[1].strip()
        member = state_member_lookup.get(normalize_struct_member_key(suffix))
        if not member:
            continue

        fake_term = BoldedTerm(
            term=member.member_name,
            file_path=term.file_path,
            line_number=term.line_number,
            requirement_id=requirement_terms.requirement_id,
            input_type=member.member_type,
            context_func_name=requirement_title,
        )
        metadata = compute_type_metadata(fake_term, enum_lookup, number_lookup, array_lookup, array_constants)
        code_member_name = struct_member_to_code_name(member.member_name)
        resolved_items.append(
            ResolvedIOItem(
                role="state",
                name=f"{requirement_title}: {raw_term}" if requirement_title else raw_term,
                data_dictionary_term=member.member_name,
                type_name=member.member_type,
                verification_identifier=f"{inferred_root_name}[0].{code_member_name}",
                type_metadata=metadata,
                requirement_id=requirement_terms.requirement_id,
                source_function=function_name or utility_key or "state",
            )
        )

    return resolved_items


def categorize_terms(terms: List[BoldedTerm]) -> Dict[str, List[str]]:
    inputs: List[str] = []
    outputs: List[str] = []
    other: List[str] = []
    input_patterns = ["input", "value", "parameter", "argument", "signal", "reference"]
    output_patterns = ["output", "result", "status", "time", "elapsed", "monitor", "count", "queue", "end"]

    for term in terms:
        lowered = term.term.lower()
        if any(p in lowered for p in input_patterns):
            inputs.append(term.term)
        elif any(p in lowered for p in output_patterns):
            outputs.append(term.term)
        else:
            other.append(term.term)

    return {
        "inputs": sorted(set(inputs)),
        "outputs": sorted(set(outputs)),
        "other": sorted(set(other)),
    }


def load_resolution_context(
    base_path: Path,
    resolve_types: bool = False,
    resolve_verification: bool = False,
    state_root_name: str = "",
) -> Dict[str, Any]:
    context: Dict[str, Any] = {
        "param_lookup": {},
        "func_lookup": {},
        "struct_lookup": {},
        "code_accessors": {},
        "enum_lookup": {},
        "number_lookup": {},
        "array_lookup": {},
        "array_constants": {},
        "verification_lookup": {},
        "term_to_files": {},
        "header_specs": {},
        "resolve_types": resolve_types,
        "resolve_verification": resolve_verification,
        "state_root_name": state_root_name,
    }

    param_lookup, func_lookup = load_data_dictionary(base_path)
    context["param_lookup"] = param_lookup
    context["func_lookup"] = func_lookup
    context["struct_lookup"] = load_struct_lookup(base_path)
    context["code_accessors"] = load_code_accessors(base_path, state_root_name or "")
    context["enum_lookup"] = load_enum_lookup(base_path)
    context["number_lookup"] = load_number_lookup(base_path)
    context["array_lookup"] = load_array_lookup(base_path)
    context["array_constants"] = load_array_constants(base_path)
    context["header_specs"] = load_header_function_specs(base_path)

    if resolve_verification:
        context["verification_lookup"] = load_verification_data_dictionary(base_path)
        context["term_to_files"] = find_verification_identifiers_in_code(base_path)

    return context


def build_requirement_payload(
    file_path: Path,
    base_path: Path,
    context: Dict[str, Any],
    resolve_types: bool = False,
    resolve_verification: bool = False,
) -> Dict[str, Any]:
    result = extract_bolded_terms(file_path)
    with open(result.file_path, "r", encoding="utf-8") as f:
        content = f.read()

    requirement_title = clean_requirement_title(extract_requirement_name(content))
    terms = result.bolded_terms

    if resolve_types:
        terms = resolve_term_types(terms, context["param_lookup"], context["func_lookup"], result.requirement_id)
        for term in terms:
            term.type_metadata = compute_type_metadata(
                term,
                context["enum_lookup"],
                context["number_lookup"],
                context["array_lookup"],
                context["array_constants"],
            )

    if resolve_verification:
        terms = resolve_verification_identifiers(
            terms,
            context["verification_lookup"],
            context["term_to_files"],
            context["param_lookup"],
            context["func_lookup"],
            result.requirement_id,
        )

    resolved_items = build_resolved_io_items(
        RequirementTerms(requirement_id=result.requirement_id, file_path=result.file_path, bolded_terms=terms),
        requirement_title,
        context["param_lookup"],
        context["func_lookup"],
        context["struct_lookup"],
        context["code_accessors"],
        context["enum_lookup"],
        context["number_lookup"],
        context["array_lookup"],
        context["array_constants"],
        context["header_specs"],
        context["state_root_name"],
    )

    expression_rows = build_expression_rows(content, terms, resolved_items)

    payload: Dict[str, Any] = {
        "file_path": result.file_path,
        "requirement_id": result.requirement_id,
        "requirement_name": requirement_title,
        "resolved_items": [
            {
                "role": item.role,
                "name": item.name,
                "data_dictionary_term": item.data_dictionary_term,
                "type": item.type_name,
                "verification_identifier": item.verification_identifier,
                "type_metadata": item.type_metadata,
                "source_function": item.source_function,
            }
            for item in resolved_items
        ],
        "expressions": expression_rows,
        "bolded_terms": [
            {
                "term": t.term,
                "line": t.line_number,
                "type": t.input_type,
                "verification_id": t.verification_id,
                "verification_files": t.verification_files,
                "type_metadata": t.type_metadata,
            }
            for t in terms
        ],
        "resolved_terms": [
            {
                "term": t.term,
                "requirement_id": t.requirement_id,
                "file_path": t.file_path,
                "input_type": t.input_type,
                "verification_id": t.verification_id,
                "verification_files": t.verification_files,
                "type_metadata": t.type_metadata,
            }
            for t in terms
        ],
    }

    payload["terms_by_role"] = {
        "inputs": [item.data_dictionary_term for item in resolved_items if item.role == "input"],
        "outputs": [item.data_dictionary_term for item in resolved_items if item.role == "output"],
        "states": [item.data_dictionary_term for item in resolved_items if item.role == "state"],
    }
    return payload


def process_requirement_files(
    base_path: Path,
    requirement_type: str = "all",
    resolve_types: bool = False,
    resolve_verification: bool = False,
    workers: int = 1,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    files = find_requirement_files(base_path, requirement_type)
    context = load_resolution_context(base_path, resolve_types, resolve_verification)

    def process_file(file_path: Path) -> Dict[str, Any]:
        return build_requirement_payload(
            file_path,
            base_path,
            context,
            resolve_types=resolve_types,
            resolve_verification=resolve_verification,
        )

    if workers and workers > 1 and len(files) > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            payloads = list(executor.map(process_file, files))
    else:
        payloads = [process_file(file_path) for file_path in files]

    all_terms: List[BoldedTerm] = []
    file_terms: Dict[str, List[str]] = {}
    resolved_terms_list: List[Dict[str, Any]] = []

    for payload in payloads:
        for term_info in payload.get("bolded_terms") or []:
            all_terms.append(
                BoldedTerm(
                    term=term_info.get("term", ""),
                    file_path=payload.get("file_path", ""),
                    line_number=int(term_info.get("line") or 0),
                    requirement_id=payload.get("requirement_id", ""),
                    input_type=term_info.get("type"),
                    verification_id=term_info.get("verification_id"),
                    verification_files=term_info.get("verification_files") or [],
                    type_metadata=term_info.get("type_metadata") or {},
                )
            )
        file_terms[payload.get("requirement_id") or Path(payload.get("file_path", "")).name] = [
            entry.get("term", "") for entry in (payload.get("bolded_terms") or [])
        ]
        resolved_terms_list.extend(payload.get("resolved_terms") or [])

    seen: set[str] = set()
    unique_terms: List[BoldedTerm] = []
    for term in all_terms:
        if term.term not in seen:
            seen.add(term.term)
            unique_terms.append(term)

    summary_data: Dict[str, Any] = {
        "total_files_processed": len(files),
        "total_unique_terms": len(unique_terms),
        "terms_by_requirement": file_terms,
        "categorized": categorize_terms(unique_terms),
        "all_terms": [t.term for t in unique_terms],
    }
    if resolve_types or resolve_verification:
        summary_data["resolved_terms"] = resolved_terms_list
    return payloads, summary_data


def extract_all_terms(
    base_path: Path,
    requirement_type: str = "all",
    resolve_types: bool = False,
    resolve_verification: bool = False,
    workers: int = 1,
) -> Dict[str, Any]:
    _payloads, summary = process_requirement_files(
        base_path,
        requirement_type,
        resolve_types=resolve_types,
        resolve_verification=resolve_verification,
        workers=workers,
    )
    return summary


def format_expression(conditions: List[str], terms: List[BoldedTerm], condition_type: str = "all") -> str:
    if not conditions:
        return "always"
    formatted: List[str] = []
    for cond in conditions:
        matched = cond
        for term in terms:
            if term.term.lower() in cond.lower() or cond.lower() in term.term.lower():
                matched = term.term
                break
        formatted.append(matched)
    if len(formatted) == 1:
        return formatted[0]
    joiner = " OR " if condition_type.lower() == "any" else " AND "
    return joiner.join(formatted)


def strip_bold_markup(text: str) -> str:
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", text or "")
    cleaned = cleaned.replace(r"\*", "*")
    return cleaned.strip()


def extract_expression_label(text: str) -> str:
    plain = strip_bold_markup(text)
    bold_match = re.search(r"\*\*([^*]+)\*\*", text or "")
    if bold_match:
        return bold_match.group(1).strip()

    for token in [" set to ", " shall ", ", when ", " when ", " is ", " are ", " shall be ", " should be "]:
        if token in plain.lower():
            return plain.split(token, 1)[0].strip()
    if "," in plain:
        return plain.split(",", 1)[0].strip()
    return plain[:80].strip()


def classify_expression_type(expression_text: str, conditions: List[str]) -> str:
    combined = " ".join([expression_text] + conditions).lower()
    plain_expression = strip_bold_markup(expression_text).lower()
    has_condition_words = bool(
        re.search(
            r"\b(when|if|otherwise|valid|invalid|null|true|false|enum|status|successful|unsuccessful|empty|non-empty|zero|non-zero|greater than|less than|equal to|not equal|set to)\b",
            combined,
        )
    )
    has_string_format = bool(
        re.search(
            r"\b(format|formatted|string input|input string|valid format|formats?\b|date format|time format)\b",
            combined,
        )
        or re.search(r'["\']\s*[a-z0-9#\-_/ ]{2,}\s*["\']', expression_text or "")
    )
    has_math = bool(
        re.search(
            r"\b(calculate|calculated|compute|computed|derive|derived|formula|sum of|difference of|product of|average of|ratio|percentage|multiply|multiplied|division|divided|square root|sqrt|arctan|atan|sin|cos|tan|unit conversion|size equal to|length equal to)\b",
            combined,
        )
        or (
            any(op in plain_expression for op in ["*", "/", "+", "-"])
            and bool(re.search(r"\b(equal to|equals|set to|computed as|calculated as|result|size|length|count|value)\b", combined))
        )
    )

    if has_math and has_string_format:
        return "math expression with string format"
    if has_string_format and has_condition_words:
        return "logical expression with string format"
    if has_math:
        return "math expression"
    if has_string_format:
        return "string format"
    return "logical expression"


def extract_expressions_from_requirement(content: str) -> List[Dict[str, Any]]:
    lines = content.splitlines()
    in_description = False
    expressions: List[Dict[str, Any]] = []
    current_expression: Optional[Dict[str, Any]] = None
    current_indent: Optional[int] = None

    for line in lines:
        stripped_line = line.rstrip()
        if stripped_line.strip().lower() == "### description":
            in_description = True
            continue
        if not in_description:
            continue
        if stripped_line.startswith("### ") and stripped_line.strip().lower() != "### description":
            break
        if not stripped_line.strip():
            continue

        bullet_match = re.match(r"^(\s*)([\*\+\-])\s+(.*)$", stripped_line)
        if not bullet_match:
            continue

        indent = len(bullet_match.group(1))
        bullet_text = bullet_match.group(3).strip()
        bullet_text = re.sub(r"\s+", " ", bullet_text)
        condition_type_match = re.match(
            r"\*\*([^*]+)\*\*\s*,\s*when\s+(any|all)\s+of\s+the\s+following\s+occur:",
            bullet_text,
            re.IGNORECASE,
        )

        is_top_level = current_expression is None or indent <= (current_indent if current_indent is not None else 0)
        if is_top_level:
            current_expression = {
                "output": extract_expression_label(bullet_text),
                "expression_text": bullet_text,
                "conditions": [],
                "condition_type": condition_type_match.group(2).lower() if condition_type_match else "any",
                "indent": indent,
            }
            expressions.append(current_expression)
            current_indent = indent
        else:
            current_expression["conditions"].append(strip_bold_markup(bullet_text))

    for entry in expressions:
        entry["expression_type"] = classify_expression_type(entry["expression_text"], entry["conditions"])

    return expressions


def is_input_term(term: str) -> bool:
    lowered = term.lower()
    return any(p in lowered for p in ["input", "value", "parameter", "argument", "signal", "reference", "lock", "element"])


def is_output_term(term: str) -> bool:
    lowered = term.lower()
    return any(p in lowered for p in ["output", "result", "status", "time", "elapsed", "monitor", "count", "queue", "end"])


def _metadata_cell(metadata: Dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    return "" if value is None else str(value)


def display_type_label(item: ResolvedIOItem) -> str:
    raw_type = (item.type_name or "").strip()
    lowered = raw_type.lower()
    metadata = item.type_metadata

    fixed_width_ints = {
        "int8_t",
        "uint8_t",
        "int16_t",
        "uint16_t",
        "int32_t",
        "uint32_t",
        "int64_t",
        "uint64_t",
    }
    generic_ints = {
        "int",
        "signed int",
        "unsigned int",
        "short",
        "unsigned short",
        "long",
        "unsigned long",
        "size_t",
        "ssize_t",
    }

    if metadata.get("array_subtype"):
        return "array"
    if metadata.get("timing_intervals"):
        return "timing"
    if metadata.get("calculation"):
        return "calculated"
    if metadata.get("string_length") or metadata.get("valid_range"):
        return "String"
    if metadata.get("enum_values") or "enum" in lowered:
        return "Enumeration"
    if lowered in ("bool", "boolean"):
        return "boolean"
    if lowered in fixed_width_ints:
        return raw_type
    if "*" in raw_type or "pointer" in lowered or "reference" in lowered:
        return "pointer"
    if lowered in generic_ints or ("int" in lowered and lowered not in fixed_width_ints):
        return "integer"
    if "float" in lowered or "double" in lowered:
        return "Float"
    if "state" in lowered:
        return "State"
    return raw_type or "unknown"


def spreadsheet_alias(index: int) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    result = ""
    value = index
    while True:
        value, remainder = divmod(value, 26)
        result = alphabet[remainder] + result
        if value == 0:
            break
        value -= 1
    return result


def extra_alias(index: int) -> str:
    return f"X{index + 1}"


def build_expression_alias_maps(
    result: RequirementTerms,
    resolved_items: List[ResolvedIOItem],
) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
    term_to_alias: Dict[str, str] = {}
    alias_to_type: Dict[str, str] = {}
    alias_to_term: Dict[str, str] = {}

    used_aliases: set[str] = set()

    def register(term: str, alias: str, type_name: str = "") -> None:
        normalized = normalize_key(term)
        if not normalized or normalized in term_to_alias:
            return
        term_to_alias[normalized] = alias
        alias_to_term[alias] = term
        if type_name:
            alias_to_type[alias] = type_name
        used_aliases.add(alias)

    input_items = [item for item in resolved_items if item.role == "input"]
    output_items = [item for item in resolved_items if item.role == "output"]
    state_items = [item for item in resolved_items if item.role == "state"]

    for idx, item in enumerate(input_items):
        alias = spreadsheet_alias(idx)
        register(item.data_dictionary_term, alias, item.type_name)
        register(item.name.rsplit(": ", 1)[-1], alias, item.type_name)
        register(item.name.split(": ", 1)[-1], alias, item.type_name)

    for idx, item in enumerate(output_items):
        alias = f"O{idx + 1}"
        register(item.data_dictionary_term, alias, item.type_name)
        register(item.name.rsplit(": ", 1)[-1], alias, item.type_name)
        register(item.name.split(": ", 1)[-1], alias, item.type_name)

    for idx, item in enumerate(state_items):
        alias = f"S{idx + 1}"
        register(item.data_dictionary_term, alias, item.type_name)
        register(item.name.rsplit(": ", 1)[-1], alias, item.type_name)
        register(item.name.split(": ", 1)[-1], alias, item.type_name)

    extra_index = 0
    for term in result.bolded_terms:
        cleaned = term.term.strip()
        if not cleaned:
            continue
        normalized = normalize_key(cleaned)
        if normalized in term_to_alias:
            continue
        alias = extra_alias(extra_index)
        extra_index += 1
        register(cleaned, alias, term.input_type or "")

    return term_to_alias, alias_to_type, alias_to_term


def replace_expression_terms(expression: str, term_to_alias: Dict[str, str]) -> str:
    replaced = strip_bold_markup(expression)
    for term in sorted(term_to_alias.keys(), key=len, reverse=True):
        alias = term_to_alias[term]
        words = term.split()
        if len(words) == 1:
            pattern_text = rf"(?<!\w){re.escape(words[0])}(?!\w)"
        else:
            pattern_text = r"(?<!\w)" + r"\W+".join(re.escape(word) for word in words) + r"(?!\w)"
        pattern = re.compile(pattern_text, re.IGNORECASE)
        replaced = pattern.sub(alias, replaced)
    replaced = replaced.replace(r"\*", "*")
    return replaced


def simplify_alias_expression(expression: str, alias_to_type: Dict[str, str]) -> str:
    simplified = re.sub(r"\s+", " ", expression).strip()

    def is_pointer_alias(alias: str) -> bool:
        type_name = alias_to_type.get(alias, "").lower()
        return "*" in type_name or "pointer" in type_name or "reference" in type_name or "queue" in type_name

    replacements = [
        (r"\b([A-Za-z][A-Za-z0-9_]*)\s+is\s+greater\s+than\s+zero\b", r"\1 > 0"),
        (r"\b([A-Za-z][A-Za-z0-9_]*)\s+is\s+less\s+than\s+zero\b", r"\1 < 0"),
        (r"\b([A-Za-z][A-Za-z0-9_]*)\s+is\s+non[- ]zero\b", r"\1 > 0"),
        (r"\b([A-Za-z][A-Za-z0-9_]*)\s+is\s+zero\b", r"\1 == 0"),
        (r"\b([A-Za-z][A-Za-z0-9_]*)\s+is\s+greater\s+than\s+or\s+equal\s+to\b", r"\1 >= "),
        (r"\b([A-Za-z][A-Za-z0-9_]*)\s+is\s+less\s+than\s+or\s+equal\s+to\b", r"\1 <= "),
        (r"\b([A-Za-z][A-Za-z0-9_]*)\s+is\s+greater\s+than\b", r"\1 > "),
        (r"\b([A-Za-z][A-Za-z0-9_]*)\s+is\s+less\s+than\b", r"\1 < "),
        (r"\b([A-Za-z][A-Za-z0-9_]*)\s+is\s+not\s+equal\s+to\b", r"\1 != "),
        (r"\b([A-Za-z][A-Za-z0-9_]*)\s+is\s+equal\s+to\b", r"\1 == "),
        (r"\b([A-Za-z][A-Za-z0-9_]*)\s+equals?\b", r"\1 == "),
    ]
    for pattern, replacement in replacements:
        simplified = re.sub(pattern, replacement, simplified, flags=re.IGNORECASE)

    simplified = re.sub(r"\b([A-Za-z][A-Za-z0-9_]*)\s+is\s+true\b", r"\1", simplified, flags=re.IGNORECASE)
    simplified = re.sub(r"\b([A-Za-z][A-Za-z0-9_]*)\s+is\s+false\b", r"NOT \1", simplified, flags=re.IGNORECASE)
    simplified = re.sub(r"\b([A-Za-z][A-Za-z0-9_]*)\s+is\s+valid\b", lambda m: f"{m.group(1)} != NULL" if is_pointer_alias(m.group(1)) else m.group(1), simplified, flags=re.IGNORECASE)
    simplified = re.sub(r"\b([A-Za-z][A-Za-z0-9_]*)\s+is\s+invalid\b", lambda m: f"{m.group(1)} == NULL" if is_pointer_alias(m.group(1)) else f"NOT {m.group(1)}", simplified, flags=re.IGNORECASE)
    simplified = re.sub(r"\b([A-Za-z][A-Za-z0-9_]*)\s+is\s+successful\b", lambda m: f"{m.group(1)} != NULL" if is_pointer_alias(m.group(1)) else m.group(1), simplified, flags=re.IGNORECASE)
    simplified = re.sub(r"\b([A-Za-z][A-Za-z0-9_]*)\s+is\s+unsuccessful\b", lambda m: f"{m.group(1)} == NULL" if is_pointer_alias(m.group(1)) else f"NOT {m.group(1)}", simplified, flags=re.IGNORECASE)

    simplified = re.sub(r"\s*([*+/()-])\s*", r" \1 ", simplified)
    simplified = re.sub(r"\bAND\b", "AND", simplified, flags=re.IGNORECASE)
    simplified = re.sub(r"\bOR\b", "OR", simplified, flags=re.IGNORECASE)
    simplified = re.sub(r"\bNOT\b", "NOT", simplified, flags=re.IGNORECASE)
    simplified = re.sub(r"\s+", " ", simplified).strip()
    return simplified


def render_table_rows(items: List[ResolvedIOItem]) -> Tuple[List[str], List[List[str]]]:
    headers = [
        "Name",
        "Type",
        "Min",
        "Max",
        "Values",
        "Enum Values",
        "Calculation",
        "Pointer Values",
        "Array Subtype",
        "Array Kind",
        "Array Length",
        "Array Formal",
        "Timing Intervals",
        "Trigger",
        "String Length",
        "Valid String Range",
        "Verification Identifier",
    ]
    rows: List[List[str]] = []
    for item in items:
        min_value = item.type_metadata.get("min_value")
        max_value = item.type_metadata.get("max_value")
        rows.append(
            [
                item.name,
                display_type_label(item),
                "" if min_value is None else str(min_value),
                "" if max_value is None else str(max_value),
                _metadata_cell(item.type_metadata, "values"),
                _metadata_cell(item.type_metadata, "enum_values"),
                _metadata_cell(item.type_metadata, "calculation"),
                _metadata_cell(item.type_metadata, "pointer_values"),
                _metadata_cell(item.type_metadata, "array_subtype"),
                _metadata_cell(item.type_metadata, "array_subtype_kind"),
                _metadata_cell(item.type_metadata, "array_length"),
                _metadata_cell(item.type_metadata, "array_formal"),
                _metadata_cell(item.type_metadata, "timing_intervals"),
                _metadata_cell(item.type_metadata, "trigger"),
                _metadata_cell(item.type_metadata, "string_length"),
                _metadata_cell(item.type_metadata, "valid_range"),
                item.verification_identifier,
            ]
        )
    return headers, rows


def print_markdown_table(title: str, items: List[ResolvedIOItem]) -> None:
    if not items:
        return

    headers, rows = render_table_rows(items)
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def render_row(row: List[str]) -> str:
        padded = [row[index].ljust(widths[index]) for index in range(len(headers))]
        return "| " + " | ".join(padded) + " |"

    separator = "|-" + "-|-".join("-" * width for width in widths) + "-|"
    print(f"\n{title}")
    print(render_row(headers))
    print(separator)
    for row in rows:
        print(render_row(row))


def resolve_expression_verification_identifier(label: str, resolved_items: List[ResolvedIOItem]) -> str:
    normalized_label = normalize_key(label)
    for item in resolved_items:
        candidates = [
            normalize_key(item.data_dictionary_term),
            normalize_key(item.name),
            normalize_key(item.name.rsplit(": ", 1)[-1]),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            if normalized_label == candidate or normalized_label.endswith(candidate) or candidate.endswith(normalized_label):
                return item.verification_identifier
    return ""


def build_expression_rows(content: str, terms: List[BoldedTerm], resolved_items: List[ResolvedIOItem]) -> List[Dict[str, str]]:
    expressions = extract_expressions_from_requirement(content)
    term_to_alias, alias_to_type, _alias_to_term = build_expression_alias_maps(
        RequirementTerms(requirement_id="", file_path="", bolded_terms=terms),
        resolved_items,
    )
    output_rows: List[Dict[str, str]] = []

    for entry in expressions:
        conditions = entry.get("conditions", [])
        output_name = entry.get("output", "")
        verification_identifier = resolve_expression_verification_identifier(output_name, resolved_items)
        condition_type = entry.get("condition_type", "any")
        joiner = " OR " if condition_type == "any" else " AND "
        if conditions:
            aliased_conditions = [simplify_alias_expression(replace_expression_terms(cond, term_to_alias), alias_to_type) for cond in conditions]
            alias_expression = joiner.join(aliased_conditions)
        else:
            alias_expression = simplify_alias_expression(
                replace_expression_terms(entry.get("expression_text", ""), term_to_alias),
                alias_to_type,
            )
        output_rows.append(
            {
                "output": output_name,
                "prompt_type": entry.get("expression_type", "logical expression"),
                "alias_expression": alias_expression,
                "source_text": entry.get("expression_text", ""),
                "verification_identifier": verification_identifier,
            }
        )

    return output_rows


def print_expression_table(content: str, terms: List[BoldedTerm], resolved_items: List[ResolvedIOItem]) -> None:
    output_rows = build_expression_rows(content, terms, resolved_items)

    if not output_rows:
        return

    headers = ["Output", "Expression Type", "Alias Expression", "Source Text", "Verification Identifier"]
    headers = ["Output", "Prompt Type", "Alias Expression", "Source Text", "Verification Identifier"]
    widths = [len(header) for header in headers]
    for row in output_rows:
        row_values = [
            row["output"],
            row["prompt_type"],
            row["alias_expression"],
            row["source_text"],
            row["verification_identifier"],
        ]
        for index, cell in enumerate(row_values):
            widths[index] = max(widths[index], len(cell))

    def render_row(row: Any) -> str:
        if isinstance(row, dict):
            row_values = [
                row["output"],
                row["prompt_type"],
                row["alias_expression"],
                row["source_text"],
                row["verification_identifier"],
            ]
        else:
            row_values = list(row)
        padded = [row_values[index].ljust(widths[index]) for index in range(len(headers))]
        return "| " + " | ".join(padded) + " |"

    separator = "|-" + "-|-".join("-" * width for width in widths) + "-|"
    print("\nEXPRESSIONS")
    print(render_row(headers))
    print(separator)
    for row in output_rows:
        print(render_row(row))


def print_single_file_result(result: RequirementTerms, args: argparse.Namespace, workspace_root: Path) -> None:
    context = load_resolution_context(workspace_root, args.resolve_types, args.resolve_verification, args.state_root_name or "")
    payload = build_requirement_payload(
        Path(result.file_path),
        workspace_root,
        context,
        resolve_types=args.resolve_types,
        resolve_verification=args.resolve_verification,
    )
    requirement_title = payload["requirement_name"]
    resolved_items = [
        ResolvedIOItem(
            role=item["role"],
            name=item["name"],
            data_dictionary_term=item["data_dictionary_term"],
            type_name=item["type"],
            verification_identifier=item["verification_identifier"],
            type_metadata=item["type_metadata"],
            source_function=item["source_function"],
        )
        for item in payload["resolved_items"]
    ]
    content = Path(result.file_path).read_text(encoding="utf-8")
    terms = result.bolded_terms
    if args.resolve_types:
        terms = resolve_term_types(terms, context["param_lookup"], context["func_lookup"], result.requirement_id)
        for term in terms:
            term.type_metadata = compute_type_metadata(
                term,
                context["enum_lookup"],
                context["number_lookup"],
                context["array_lookup"],
                context["array_constants"],
            )
    if args.resolve_verification:
        terms = resolve_verification_identifiers(
            terms,
            context["verification_lookup"],
            context["term_to_files"],
            context["param_lookup"],
            context["func_lookup"],
            result.requirement_id,
        )

    inputs = [item for item in resolved_items if item.role == "input"]
    outputs = [item for item in resolved_items if item.role == "output"]
    states = [item for item in resolved_items if item.role == "state"]

    print(f"\nRequirement ID = {result.requirement_id}")
    print(f"Requirement name = {requirement_title}")
    print(f"Bolded terms found = {len(result.bolded_terms)}")

    if inputs:
        print_markdown_table("INPUTS", inputs)

    if outputs:
        print_markdown_table("OUTPUTS", outputs)

    if states:
        print_markdown_table("STATE", states)

    print_expression_table(content, terms, resolved_items)
    expression_rows = build_expression_rows(content, terms, resolved_items)

    if not inputs and not outputs:
        print("\nNo resolvable input/output terms were found.")
        if result.bolded_terms:
            for term in result.bolded_terms:
                print(f" - {term.term} (line {term.line_number})")

    if args.output:
        payload = {
            "file_path": result.file_path,
            "requirement_id": result.requirement_id,
            "requirement_name": requirement_title,
            "resolved_items": payload["resolved_items"],
            "expressions": expression_rows,
            "bolded_terms": payload["bolded_terms"],
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"Results saved to: {args.output}")

    if args.per_file_output_dir:
        output_dir = Path(args.per_file_output_dir).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_name = f"test_{sanitize_identifier(result.requirement_id or Path(result.file_path).stem)}.json"
        with (output_dir / output_name).open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"Per-file JSON saved to: {output_dir / output_name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract bolded terms from requirement files")
    parser.add_argument("--file", "-f", type=str, help="Extract from specific file")
    parser.add_argument("--requirement-id", type=str, help="Extract from requirement file by ID")
    parser.add_argument("--llr", action="store_true", help="Extract from LLR requirements only")
    parser.add_argument("--hlr", action="store_true", help="Extract from HLR requirements only")
    parser.add_argument("--all", action="store_true", help="Extract from all requirements")
    parser.add_argument("--resolve-types", action="store_true", help="Resolve types from data dictionary")
    parser.add_argument("--resolve-verification", action="store_true", help="Resolve verification identifiers")
    parser.add_argument("--human-readable", action="store_true", help="Output in human-readable format")
    parser.add_argument("--output", "-o", type=str, help="Output file for JSON results")
    parser.add_argument("--per-file-output-dir", type=str, help="Write one JSON payload per requirement to this directory")
    parser.add_argument("--workers", type=int, default=max(1, min(8, (os.cpu_count() or 1))), help="Worker count for batch processing")
    parser.add_argument("--workspace", type=str, default=".", help="Workspace root directory")
    parser.add_argument("--state-root-name", type=str, default="", help="Override the root object name used for array-backed verification identifiers")
    args = parser.parse_args()

    workspace_root = Path(args.workspace).resolve()
    req_type = "llr" if args.llr else "hlr" if args.hlr else "all"

    if args.requirement_id:
        file_path = find_requirement_by_id(workspace_root, args.requirement_id)
        if not file_path:
            print(f"Error: Requirement {args.requirement_id} not found")
            return
        print(f"Found requirement {args.requirement_id} at: {file_path}")
        result = extract_bolded_terms(file_path)
        param_lookup, func_lookup = load_data_dictionary(workspace_root)
        enum_lookup = load_enum_lookup(workspace_root)
        number_lookup = load_number_lookup(workspace_root)
        array_lookup = load_array_lookup(workspace_root)
        array_constants = load_array_constants(workspace_root)

        if args.resolve_types:
            result.bolded_terms = resolve_term_types(result.bolded_terms, param_lookup, func_lookup, result.requirement_id)
            for term in result.bolded_terms:
                term.type_metadata = compute_type_metadata(term, enum_lookup, number_lookup, array_lookup, array_constants)
        if args.resolve_verification:
            verification_lookup = load_verification_data_dictionary(workspace_root)
            term_to_files = find_verification_identifiers_in_code(workspace_root)
            result.bolded_terms = resolve_verification_identifiers(
                result.bolded_terms,
                verification_lookup,
                term_to_files,
                param_lookup,
                func_lookup,
                result.requirement_id,
            )
        print_single_file_result(result, args, workspace_root)
        return

    if args.file:
        file_path = Path(args.file)
        if not file_path.is_absolute():
            file_path = workspace_root / file_path
        result = extract_bolded_terms(file_path)
        param_lookup, func_lookup = load_data_dictionary(workspace_root)
        enum_lookup = load_enum_lookup(workspace_root)
        number_lookup = load_number_lookup(workspace_root)
        array_lookup = load_array_lookup(workspace_root)
        array_constants = load_array_constants(workspace_root)

        if args.resolve_types:
            result.bolded_terms = resolve_term_types(result.bolded_terms, param_lookup, func_lookup, result.requirement_id)
            for term in result.bolded_terms:
                term.type_metadata = compute_type_metadata(term, enum_lookup, number_lookup, array_lookup, array_constants)
        if args.resolve_verification:
            verification_lookup = load_verification_data_dictionary(workspace_root)
            term_to_files = find_verification_identifiers_in_code(workspace_root)
            result.bolded_terms = resolve_verification_identifiers(
                result.bolded_terms,
                verification_lookup,
                term_to_files,
                param_lookup,
                func_lookup,
                result.requirement_id,
            )
        print_single_file_result(result, args, workspace_root)
        return

    per_file_output_dir = Path(args.per_file_output_dir).expanduser().resolve() if args.per_file_output_dir else None
    if per_file_output_dir:
        per_file_output_dir.mkdir(parents=True, exist_ok=True)
        payloads, results = process_requirement_files(
            workspace_root,
            req_type,
            resolve_types=args.resolve_types,
            resolve_verification=args.resolve_verification,
            workers=args.workers,
        )
        for payload in payloads:
            output_name = f"test_{sanitize_identifier(payload.get('requirement_id') or Path(payload.get('file_path', '')).stem)}.json"
            out_path = per_file_output_dir / output_name
            with out_path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        print(f"\nWrote {len(payloads)} per-file JSON payloads to: {per_file_output_dir}")
    else:
        results = extract_all_terms(
            workspace_root,
            req_type,
            args.resolve_types,
            args.resolve_verification,
            workers=args.workers,
        )
    print("\n" + "=" * 60)
    print("BOLDED TERMS EXTRACTION RESULTS")
    print("=" * 60)
    print(f"\nFiles processed: {results['total_files_processed']}")
    print(f"Unique terms found: {results['total_unique_terms']}")
    print("\n--- Categorized Terms ---")
    print(f"\nInputs ({len(results['categorized']['inputs'])}):")
    for term in results["categorized"]["inputs"][:20]:
        print(f" - {term}")
    if len(results["categorized"]["inputs"]) > 20:
        print(f" ... and {len(results['categorized']['inputs']) - 20} more")
    print(f"\nOutputs ({len(results['categorized']['outputs'])}):")
    for term in results["categorized"]["outputs"][:20]:
        print(f" - {term}")
    if len(results["categorized"]["outputs"]) > 20:
        print(f" ... and {len(results['categorized']['outputs']) - 20} more")
    print(f"\nOther ({len(results['categorized']['other'])}):")
    for term in results["categorized"]["other"][:20]:
        print(f" - {term}")
    if len(results["categorized"]["other"]) > 20:
        print(f" ... and {len(results['categorized']['other']) - 20} more")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    main()
