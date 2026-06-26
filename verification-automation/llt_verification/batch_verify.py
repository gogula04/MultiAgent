#!/usr/bin/env python3
"""
Batch LLT Verification - Process all requirements in the repository.

Usage:
 python batch_verify.py # Process all LLR requirements
 python batch_verify.py --testable-only # Only show testable requirements
 python batch_verify.py --step2 FAF-LLR-xxx # Show Step 2 for specific requirement
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List

from llt_verification import RequirementEvaluator


def find_all_requirement_ids(llr_dir: Path) -> List[str]:
    """Find all requirement IDs in the LLR directory."""
    req_ids = []
    for req_file in llr_dir.rglob("*.md"):
        match = re.search(r"(FAF-LLR-\d+)", req_file.name)
        if match:
            req_ids.append(match.group(1))
    return sorted(set(req_ids))


def batch_verify(workspace_root: str = None, testable_only: bool = False) -> Dict:
    """Process all requirements and return summary."""
    evaluator = RequirementEvaluator(workspace_root)

    llr_dir = Path(evaluator.workspace_root) / "requirements" / "LLR"
    if not llr_dir.exists():
        llr_dir = Path(evaluator.workspace_root)
    req_ids = find_all_requirement_ids(llr_dir)

    results = {
        "total_requirements": len(req_ids),
        "testable_count": 0,
        "not_testable_count": 0,
        "not_found_count": 0,
        "direct_method_count": 0,
        "hybrid_method_count": 0,
        "requirements": [],
    }

    for req_id in req_ids:
        description, req_path = evaluator.find_requirement_by_id(req_id)
        if not description:
            results["not_found_count"] += 1
            continue

        result = evaluator.evaluate(description)
        result["requirement_id"] = req_id
        result["requirement_file"] = str(req_path)

        if result["testable"]:
            component_name = evaluator.extract_component_name(description)
            method_decision = evaluator.make_method_decision(result, component_name)
            result["method_decision"] = method_decision

            if method_decision["selected_method"] == "direct":
                results["direct_method_count"] += 1
            elif method_decision["selected_method"] == "hybrid":
                results["hybrid_method_count"] += 1

            results["testable_count"] += 1
        else:
            results["not_testable_count"] += 1

        if not testable_only or result["testable"]:
            results["requirements"].append(result)

    return results


def main():
    """Main entry point for batch verification."""
    testable_only = "--testable-only" in sys.argv
    sys.argv = [arg for arg in sys.argv if arg != "--testable-only"]

    results = batch_verify(testable_only=testable_only)

    print(f"Total Requirements: {results['total_requirements']}")
    print(f"Testable: {results['testable_count']}")
    print(f"Not Testable: {results['not_testable_count']}")
    print(f"Not Found: {results['not_found_count']}")
    print(f"Direct Method: {results['direct_method_count']}")
    print(f"Hybrid Method: {results['hybrid_method_count']}")
    print()

    if results["requirements"]:
        print("Sample testable requirements:")
        for req in results["requirements"][:10]:
            method = req.get("method_decision", {}).get("selected_method", "unknown")
            print(f" - {req['requirement_id']}: {req['classification']} (method: {method})")


if __name__ == "__main__":
    main()
