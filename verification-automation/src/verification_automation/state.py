"""Mutable state passed between agents."""

from __future__ import annotations

from typing import TypedDict, NotRequired


class VerificationState(TypedDict, total=False):
    requirement_identifier: str
    requirement_name: str
    requirement_text: str
    source_snippet: str
    resolved_requirement: dict
    requirement_resolution_status: str
    requirement_resolution_notes: str
    requirement_matches: list[str]
    requirement_bold_terms: list[str]
    output_dir: str
    component_name: str
    signature: str
    function_name: str
    function_return_type: str
    related_requirements: list[str]

    discovered_files: list[dict]
    behaviors: list[dict]
    mappings: list[dict]
    dd_rows: list[dict]
    mode: str
    mode_override: str
    artifact_plan: dict

    rvstest_text: str
    python_test_text: str
    uut_dictionary_text: str
    data_dictionary_text: str
    rapita_config_text: str
    rapita_node_mapping_text: str
    traceability_notes_text: str
    review_status: str
    review_notes: str
    review_decision: dict

    test_results: dict
    coverage: list[dict]
    artifacts: dict[str, str]
    rapita_plan: list[dict]
    rapita_results: dict
    failure_classification: list[dict]
    suggested_fix_report: str
    assumptions: list[str]
    unresolved: list[str]
    manual_review: list[str]
    learning_status: str
    learning_summary_text: str
    learning_record: dict
    learning_artifacts: dict
    learning_store_path: str
    proof_report: dict
    status: str
    repair_attempts: int
    logs: NotRequired[list[str]]
