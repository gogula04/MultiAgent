#!/usr/bin/env python3
"""
End-to-end batch pipeline.

Runs requirement extraction and testcase generation together in one command.
"""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Tuple

from bolded_terms_extractor import (
    build_requirement_payload,
    extract_bolded_terms,
    find_requirement_by_id,
    find_requirement_files,
    load_resolution_context,
    process_requirement_files,
    sanitize_identifier,
)
from testcase_generator_agent import generate_test_file


def requirement_scope(args: argparse.Namespace) -> str:
    if args.llr:
        return "llr"
    if args.hlr:
        return "hlr"
    return "all"


def single_requirement_payload(
    workspace_root: Path,
    file_path: Path,
    resolve_types: bool,
    resolve_verification: bool,
    state_root_name: str,
) -> Dict[str, Any]:
    context = load_resolution_context(workspace_root, resolve_types, resolve_verification, state_root_name)
    return build_requirement_payload(
        file_path,
        workspace_root,
        context,
        resolve_types=resolve_types,
        resolve_verification=resolve_verification,
    )


def write_json_payload(payload: Dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    requirement_id = payload.get("requirement_id") or Path(payload.get("file_path", "")).stem
    output_path = output_dir / f"test_{sanitize_identifier(requirement_id)}.json"
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def write_test_file(payload: Dict[str, Any], output_dir: Path, component_name: str = "") -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    requirement_id = payload.get("requirement_id") or Path(payload.get("file_path", "")).stem
    output_path = output_dir / f"test_{sanitize_identifier(requirement_id)}.py"
    output_path.write_text(generate_test_file(payload, component_override=component_name), encoding="utf-8")
    return output_path


def build_batch_payloads(
    workspace_root: Path,
    args: argparse.Namespace,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if args.requirement_id:
        file_path = find_requirement_by_id(workspace_root, args.requirement_id)
        if not file_path:
            raise FileNotFoundError(f"Requirement {args.requirement_id} not found")
        payload = single_requirement_payload(
            workspace_root,
            file_path,
            args.resolve_types,
            args.resolve_verification,
            args.state_root_name or "",
        )
        summary = {
            "total_files_processed": 1,
            "total_unique_terms": len(payload.get("bolded_terms") or []),
            "terms_by_requirement": {payload.get("requirement_id") or file_path.name: [t.get("term", "") for t in payload.get("bolded_terms") or []]},
            "categorized": {"inputs": [], "outputs": [], "other": []},
            "all_terms": [t.get("term", "") for t in payload.get("bolded_terms") or []],
        }
        return [payload], summary

    if args.file:
        file_path = Path(args.file).expanduser().resolve()
        if not file_path.is_absolute():
            file_path = workspace_root / file_path
        payload = single_requirement_payload(
            workspace_root,
            file_path,
            args.resolve_types,
            args.resolve_verification,
            args.state_root_name or "",
        )
        summary = {
            "total_files_processed": 1,
            "total_unique_terms": len(payload.get("bolded_terms") or []),
            "terms_by_requirement": {payload.get("requirement_id") or file_path.name: [t.get("term", "") for t in payload.get("bolded_terms") or []]},
            "categorized": {"inputs": [], "outputs": [], "other": []},
            "all_terms": [t.get("term", "") for t in payload.get("bolded_terms") or []],
        }
        return [payload], summary

    payloads, summary = process_requirement_files(
        workspace_root,
        requirement_scope(args),
        resolve_types=args.resolve_types,
        resolve_verification=args.resolve_verification,
        workers=args.workers,
    )
    return payloads, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run extraction and testcase generation together")
    parser.add_argument("--workspace", type=str, default=".", help="Workspace root directory")
    parser.add_argument("--file", type=str, help="Run on a specific requirement markdown file")
    parser.add_argument("--requirement-id", type=str, help="Run on a requirement by ID")
    parser.add_argument("--llr", action="store_true", help="Process LLR requirements only")
    parser.add_argument("--hlr", action="store_true", help="Process HLR requirements only")
    parser.add_argument("--all", action="store_true", help="Process all requirements")
    parser.add_argument("--resolve-types", action="store_true", help="Resolve types from data dictionary")
    parser.add_argument("--resolve-verification", action="store_true", help="Resolve verification identifiers")
    parser.add_argument("--state-root-name", type=str, default="", help="Override the root object name used for array-backed verification identifiers")
    parser.add_argument("--json-dir", type=str, help="Optional directory to save extractor JSON payloads")
    parser.add_argument("--output-dir", type=str, default=str(Path.home() / "Downloads"), help="Directory to write generated testcase files")
    parser.add_argument("--component-name", type=str, help="Override FW.Set_Component value")
    parser.add_argument("--workers", type=int, default=max(1, min(8, (os.cpu_count() or 1))), help="Worker count for extraction and generation")
    args = parser.parse_args()

    workspace_root = Path(args.workspace).expanduser().resolve()
    payloads, summary = build_batch_payloads(workspace_root, args)

    json_dir = Path(args.json_dir).expanduser().resolve() if args.json_dir else None
    if json_dir:
        for payload in payloads:
            write_json_payload(payload, json_dir)
        print(f"Wrote {len(payloads)} extractor JSON files to: {json_dir}")

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    def render(payload: Dict[str, Any]) -> Path:
        return write_test_file(payload, output_dir, component_name=args.component_name or "")

    if args.workers > 1 and len(payloads) > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            outputs = list(executor.map(render, payloads))
    else:
        outputs = [render(payload) for payload in payloads]

    print(f"Generated {len(outputs)} testcase files to: {output_dir}")
    print(f"Files processed: {summary.get('total_files_processed', len(payloads))}")


if __name__ == "__main__":
    main()
