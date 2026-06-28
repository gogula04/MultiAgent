"""Validation helpers for LLT multi-agent handoffs."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


CONTRACT_KEYS: Dict[str, List[str]] = {
    "requirement_package": [
        "requirement_id",
        "requirement_text",
        "classification",
        "inputs",
        "outputs",
        "bold_terms",
        "types_and_ranges",
        "expressions",
        "extraction_contract",
        "component_name",
        "status",
    ],
    "evidence_package": [
        "requirement_id",
        "classification",
        "inputs",
        "outputs",
        "data_dictionary_findings",
        "source_file_findings",
        "uut_dictionary_findings",
        "testability_analysis",
        "status",
    ],
    "normalized_terms_package": [
        "requirement_id",
        "normalized_terms",
        "aliases",
        "status",
    ],
    "analysis_package": [
        "requirement_id",
        "summary",
        "key_signals",
        "likely_method",
        "risks",
        "recommendations",
        "status",
    ],
    "strategy_decision": [
        "requirement_id",
        "selected_method",
        "reason",
        "evidence",
        "status",
    ],
    "artifact_patch": [
        "requirement_id",
        "selected_method",
        "files_created",
        "files_updated",
        "status",
    ],
    "traceability_result": [
        "requirement_id",
        "passed",
        "issues",
        "status",
    ],
    "execution_result": [
        "requirement_id",
        "status",
        "command",
        "exit_code",
        "stdout",
        "stderr",
    ],
    "debug_result": [
        "requirement_id",
        "status",
        "attempts",
        "changes",
        "execution_result",
    ],
    "review_result": [
        "requirement_id",
        "status",
        "summary",
        "issues",
        "recommendations",
    ],
    "proof_report": [
        "requirement_id",
        "status",
        "method_decision",
        "method_proof",
        "artifacts",
        "review",
        "execution_result",
        "generated_files",
        "logs",
    ],
}


def require_keys(payload: Dict[str, Any], required: Iterable[str], label: str) -> None:
    """Raise a clear error when a package is missing required keys."""
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"{label} missing required keys: {', '.join(missing)}")


def validate_contract(label: str, payload: Dict[str, Any]) -> None:
    """Validate a payload against the known contract keys."""
    required = CONTRACT_KEYS.get(label)
    if required:
        require_keys(payload, required, label)
