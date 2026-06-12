"""Core data models for the verification workflow."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(slots=True)
class RequirementInput:
    identifier: str
    text: str = ""
    source_snippet: str = ""


@dataclass(slots=True)
class DiscoveredFile:
    path: str
    kind: str
    relevance: float = 0.0
    notes: str = ""


@dataclass(slots=True)
class RequirementBehavior:
    label: str
    description: str
    terms: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MappingRow:
    requirement_term: str
    source_term: str
    implementation: str
    dd_entry: str
    reason: str


@dataclass(slots=True)
class DDRow:
    requirement_name: str = ""
    verification_identifier: str = ""
    element_type: str = ""
    stub_reference: str = ""
    base_data_type: str = ""
    leaf_data_type: str = ""
    name: str = ""
    status: str = ""
    source_mapping: str = ""
    purpose: str = ""


@dataclass(slots=True)
class UUTRow:
    uut_name: str
    rate: str = "1.0"
    initFcn: str = ""
    return_type: str = "void"
    step_fcn: str = ""
    return_stepfn: str = ""
    mockFcns: str = ""
    preconditions: str = ""
    signature: str = ""


@dataclass(slots=True)
class CoverageItem:
    item: str
    status: str
    notes: str = ""


@dataclass(slots=True)
class ProofReport:
    requirement_id: str
    requirement_name: str
    mode: str
    summary: str
    review_status: str = ""
    review_notes: str = ""
    mappings: list[MappingRow] = field(default_factory=list)
    dd_rows: list[DDRow] = field(default_factory=list)
    discovered_files: list[DiscoveredFile] = field(default_factory=list)
    coverage: list[CoverageItem] = field(default_factory=list)
    test_results: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    rapita_plan: list[dict[str, Any]] = field(default_factory=list)
    rapita_results: dict[str, Any] = field(default_factory=dict)
    failure_classification: list[dict[str, Any]] = field(default_factory=list)
    suggested_fix_report: str = ""
    assumptions: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    manual_review: list[str] = field(default_factory=list)
    conclusion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
