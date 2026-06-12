"""Agent step implementations for the verification workflow."""

from __future__ import annotations

from dataclasses import asdict
import re
from pathlib import Path
from typing import Any

from .artifacts import (
    render_data_dictionary_csv,
    render_proof_markdown,
    render_python_tests,
    render_rvstest_setup,
    render_traceability_notes,
    render_uut_dictionary_csv,
)
from .config import AppConfig
from .models import (
    CoverageItem,
    DDRow,
    DiscoveredFile,
    MappingRow,
    ProofReport,
    RequirementBehavior,
    RequirementInput,
    UUTRow,
)
from .provider import ModelAdapter, get_model
from .rapita_assets import render_node_mapping, render_rvsconfig_xml
from .repo_scan import RepoDiscovery, scan_repository
from .state import VerificationState
from .coverage import analyze_verification_coverage
from .learning import learn_from_run
from .rag import build_evidence_bundle
from .requirement_resolver import resolve_requirement


def intake_requirement(state: VerificationState) -> VerificationState:
    identifier = (state.get("requirement_identifier") or "").strip()
    text = (state.get("requirement_text") or "").strip()
    snippet = (state.get("source_snippet") or "").strip()
    requirement_name = _extract_requirement_name(text) or identifier
    state["requirement_identifier"] = identifier or text[:80] or "UNSPECIFIED"
    state["requirement_name"] = requirement_name or state["requirement_identifier"]
    state["requirement_text"] = text
    state["source_snippet"] = snippet
    state["signature"] = snippet
    state["function_name"] = _derive_function_name(identifier, text, snippet)
    state["function_return_type"] = _derive_return_type(snippet)
    state["component_name"] = state["requirement_name"] or state["function_name"] or identifier or "VerificationComponent"
    state["related_requirements"] = state.get("related_requirements", [])
    state.setdefault("logs", []).append("Requirement intake complete.")
    return state


def resolve_requirement_state(state: VerificationState, config: AppConfig) -> VerificationState:
    repo_root = config.repo_root.expanduser()
    resolved = resolve_requirement(
        repo_root,
        state.get("requirement_identifier", ""),
        requirement_text=state.get("requirement_text", ""),
        source_snippet=state.get("source_snippet", ""),
    )
    state["resolved_requirement"] = resolved.to_dict()
    state["requirement_resolution_status"] = "resolved" if resolved.found else "unresolved"
    state["requirement_resolution_notes"] = resolved.notes
    state["requirement_matches"] = list(resolved.matched_lines or [])
    state["requirement_bold_terms"] = list(resolved.bold_terms or [])
    if resolved.found:
        state["requirement_name"] = resolved.name or state.get("requirement_name", "")
        if resolved.text and not state.get("requirement_text"):
            state["requirement_text"] = resolved.text
        state.setdefault("logs", []).append(
            f"Requirement resolved from repo: {resolved.file_path or 'provided text'}."
        )
    else:
        state.setdefault("unresolved", []).append(resolved.notes)
        if not state.get("requirement_text", "").strip() and not state.get("source_snippet", "").strip():
            state["status"] = "blocked"
            state["review_status"] = "not reviewed"
            state["review_notes"] = resolved.notes
            state["review_decision"] = {
                "is_safe": False,
                "risk_score": 10,
                "summary": resolved.notes,
                "suggested_fix": "Select the company repo root or paste the full requirement text.",
                "tags": ["blocked", "resolution", "repository"],
            }
            state["proof_report"] = {
                "summary": "No proof generated.",
                "conclusion": resolved.notes,
                "coverage": [],
                "test_results": {},
            }
    return state


def discover_repository(state: VerificationState, config: AppConfig) -> VerificationState:
    req = RequirementInput(
        identifier=state["requirement_identifier"],
        text=state.get("requirement_text", ""),
        source_snippet=state.get("source_snippet", ""),
    )
    keywords = [req.identifier, *req.text.split()[:8], *req.source_snippet.split()[:8]]
    discovery = scan_repository(config.repo_root, keywords=keywords)
    retrieval = build_evidence_bundle(
        config.repo_root,
        req,
        discovery.requirement_files + discovery.source_files + discovery.dictionary_files + discovery.test_files + discovery.harness_files,
        resolved_requirement=state.get("resolved_requirement", {}),
        output_dir=Path(state.get("output_dir", config.repo_root / "artifacts")),
    )
    state["discovered_files"] = [
        asdict(item)
        for item in (
            discovery.requirement_files
            + discovery.source_files
            + discovery.dictionary_files
            + discovery.test_files
            + discovery.harness_files
        )
    ]
    state["retrieval_hits"] = [asdict(item) for item in retrieval.hits]
    state["evidence_bundle"] = retrieval.to_dict()
    state["evidence_status"] = "ready" if retrieval.supports_generation else "blocked"
    state["evidence_summary"] = retrieval.summary
    if retrieval.same_function_hits or retrieval.same_module_hits:
        evidence_examples = [
            DiscoveredFile(
                path=item.path,
                kind=item.kind,
                relevance=item.score,
                notes=item.reason,
                excerpt=item.excerpt,
                source=item.source,
            )
            for item in retrieval.same_function_hits + retrieval.same_module_hits
        ]
        state["discovered_files"].extend(asdict(item) for item in evidence_examples)
    state.setdefault("logs", []).append(
        f"Repository discovery found {len(state['discovered_files'])} candidate files."
    )
    state["logs"].append(f"Retrieval summary: {retrieval.summary}")
    if not retrieval.supports_generation:
        reason = retrieval.blocking_reason or "Insufficient repository evidence for generation."
        state["status"] = "blocked"
        state["review_status"] = "not reviewed"
        state["review_notes"] = reason
        state["review_decision"] = {
            "is_safe": False,
            "risk_score": 10,
            "summary": reason,
            "suggested_fix": "Use a repo that contains matching requirements, source, dictionary, and verified example evidence.",
            "tags": ["blocked", "evidence", "repository"],
        }
        state["proof_report"] = {
            "summary": "No proof generated.",
            "conclusion": reason,
            "coverage": [],
            "test_results": {},
        }
        state.setdefault("unresolved", []).append(reason)
        state.setdefault("manual_review", []).append(reason)
    return state


def parse_requirement(state: VerificationState, model: ModelAdapter) -> VerificationState:
    req = RequirementInput(
        identifier=state["requirement_identifier"],
        text=state.get("requirement_text", ""),
        source_snippet=state.get("source_snippet", ""),
    )
    files = _files_from_state(state)
    behaviors = model.analyze_requirement(req, files)
    state["behaviors"] = [asdict(item) for item in behaviors]
    state.setdefault("logs", []).append(f"Parsed {len(behaviors)} requirement behavior blocks.")
    return state


def map_source_and_dictionaries(state: VerificationState, model: ModelAdapter) -> VerificationState:
    req = RequirementInput(
        identifier=state["requirement_identifier"],
        text=state.get("requirement_text", ""),
        source_snippet=state.get("source_snippet", ""),
    )
    files = _files_from_state(state)
    behaviors = [RequirementBehavior(**row) for row in state.get("behaviors", [])]
    mappings = model.map_requirement(req, behaviors, files)
    state["mappings"] = [asdict(item) for item in mappings]
    state.setdefault("logs", []).append(f"Built {len(mappings)} traceability mappings.")
    return state


def select_strategy(state: VerificationState, model: ModelAdapter) -> VerificationState:
    req = RequirementInput(
        identifier=state["requirement_identifier"],
        text=state.get("requirement_text", ""),
        source_snippet=state.get("source_snippet", ""),
    )
    override = (state.get("mode_override") or "").strip().lower()
    evidence_bundle = state.get("evidence_bundle", {})
    if override in {"direct", "hybrid", "manual"}:
        mode = override.capitalize()
        state["mode"] = mode
        state["artifact_plan"] = {
            "mode": mode,
            "needs_uut_dictionary": mode == "Direct",
            "needs_rvstest": mode in {"Hybrid", "Manual"},
            "needs_python": mode in {"Direct", "Hybrid"},
        }
        state.setdefault("logs", []).append(f"Verification mode overridden to: {mode}.")
        return state
    if isinstance(evidence_bundle, dict) and evidence_bundle.get("recommended_mode"):
        mode = str(evidence_bundle["recommended_mode"])
    else:
        text = " ".join([req.identifier, req.text, req.source_snippet]).lower()
        has_harness = any(item["kind"] == "harness" for item in state.get("discovered_files", []))
        has_pointer_terms = any(term in text for term in ("pointer", "null", "reference", "output", "struct", "mutex", "lock", "queue"))
        has_helper_terms = any(term in text for term in ("stub", "helper", "lognonseverefault", "mutextrylock", "mutexlock", "mutexunlock"))
        has_manual_hint = any(term in text for term in ("manual", "vector", "procedure", "rvstest"))
        if has_manual_hint and has_harness:
            mode = "Manual"
        elif has_harness or has_helper_terms or has_pointer_terms:
            mode = "Hybrid"
        else:
            mode = "Direct"
    state["mode"] = mode
    state["artifact_plan"] = {
        "mode": mode,
        "needs_uut_dictionary": mode == "Direct",
        "needs_rvstest": mode in {"Hybrid", "Manual"},
        "needs_python": mode in {"Direct", "Hybrid"},
    }
    if evidence_bundle:
        state.setdefault("logs", []).append(
            f"Selected verification mode: {mode} using evidence bundle confidence {evidence_bundle.get('confidence', 0)}."
        )
    else:
        state.setdefault("logs", []).append(f"Selected verification mode: {mode}.")
    return state


def build_dd(state: VerificationState, model: ModelAdapter) -> VerificationState:
    req = RequirementInput(
        identifier=state["requirement_identifier"],
        text=state.get("requirement_text", ""),
        source_snippet=state.get("source_snippet", ""),
    )
    mappings = [MappingRow(**row) for row in state.get("mappings", [])]
    behaviors = [RequirementBehavior(**row) for row in state.get("behaviors", [])]
    dd_rows = model.build_dd(req, mappings, state.get("mode", "Direct"), behaviors=behaviors)
    requirement_name = state.get("requirement_name", req.identifier)
    for row in dd_rows:
        row.requirement_name = requirement_name
    state["dd_rows"] = [asdict(item) for item in dd_rows]
    state["data_dictionary_text"] = render_data_dictionary_csv(dd_rows)
    state["uut_dictionary_text"] = (
        render_uut_dictionary_csv(
            UUTRow(
                uut_name=state.get("component_name", req.identifier),
                rate="1.0",
                initFcn="",
                return_type="void",
                step_fcn=state.get("function_name", req.identifier),
                return_stepfn=state.get("function_return_type", "void"),
                    mockFcns="",
                    preconditions="",
                    signature=state.get("signature", ""),
                )
        )
        if state.get("mode") == "Direct"
        else ""
    )
    state.setdefault("logs", []).append(f"Generated {len(dd_rows)} DD rows.")
    return state


def build_setup_and_tests(state: VerificationState, config: AppConfig) -> VerificationState:
    req = RequirementInput(
        identifier=state["requirement_identifier"],
        text=state.get("requirement_text", ""),
        source_snippet=state.get("source_snippet", ""),
    )
    mappings = [MappingRow(**row) for row in state.get("mappings", [])]
    dd_rows = [DDRow(**row) for row in state.get("dd_rows", [])]
    behaviors = [RequirementBehavior(**row) for row in state.get("behaviors", [])]
    mode = state.get("mode", "Direct")
    component_name = state.get("component_name", req.identifier)
    if mode in {"Hybrid", "Manual"}:
        component_name = _select_harness_component(state, req.identifier)
        state["component_name"] = component_name
    if mode in {"Hybrid", "Manual"}:
        state["rvstest_text"] = render_rvstest_setup(component_name, req.identifier, mappings, dd_rows, mode)
    else:
        state["rvstest_text"] = ""
    if mode in {"Direct", "Hybrid"}:
        state["python_test_text"] = render_python_tests(req.identifier, req.identifier, state.get("component_name", req.identifier), mappings, dd_rows, behaviors, mode)
    else:
        state["python_test_text"] = ""
    state["rapita_config_text"] = render_rvsconfig_xml()
    state["rapita_node_mapping_text"] = render_node_mapping(config, state.get("component_name", req.identifier))
    state["traceability_notes_text"] = render_traceability_notes(
        state.get("requirement_identifier", req.identifier),
        state.get("requirement_name", req.identifier),
        mode,
        mappings,
        dd_rows,
        resolved_requirement=state.get("resolved_requirement", {}),
        bold_terms=state.get("requirement_bold_terms", []),
    )
    state.setdefault("logs", []).append("Generated setup and test artifacts.")
    return state


def review_drafts(state: VerificationState, model: ModelAdapter, config: AppConfig) -> VerificationState:
    req = RequirementInput(
        identifier=state["requirement_identifier"],
        text=state.get("requirement_text", ""),
        source_snippet=state.get("source_snippet", ""),
    )
    draft = {
        "data_dictionary": state.get("data_dictionary_text", ""),
        "uut_dictionary": state.get("uut_dictionary_text", ""),
        "rvstest": state.get("rvstest_text", ""),
        "python_test": state.get("python_test_text", ""),
        "rapita_config": state.get("rapita_config_text", ""),
        "rapita_node_mapping": state.get("rapita_node_mapping_text", ""),
        "traceability_notes": state.get("traceability_notes_text", ""),
        "mappings": state.get("mappings", []),
        "dd_rows": state.get("dd_rows", []),
    }
    review = model.review_drafts(req, draft, config)
    auto_approve = config.auto_approve
    approved = bool(review.get("is_safe", True)) and auto_approve
    if auto_approve and not review.get("is_safe", True):
        approved = False
    state["review_status"] = "approved" if approved else "pending_review"
    state["review_notes"] = review.get("summary", "")
    state["review_decision"] = review
    if approved:
        state.setdefault("logs", []).append("Human review gate approved draft artifacts.")
    else:
        state.setdefault("logs", []).append("Human review gate requires approval.")
        state["status"] = "awaiting_review"
    return state


def analyze_coverage(state: VerificationState, model: ModelAdapter) -> VerificationState:
    del model
    return analyze_verification_coverage(state)


def build_proof(state: VerificationState, model: ModelAdapter) -> VerificationState:
    del model
    results = state.get("test_results", {})
    rapita_results = state.get("rapita_results", {})
    report = ProofReport(
        requirement_id=state.get("requirement_identifier", ""),
        requirement_name=state.get("requirement_name", state.get("requirement_identifier", "")),
        mode=state.get("mode", "Direct"),
        summary=(
            f"Verification automation completed for {state.get('requirement_identifier', 'UNSPECIFIED')}. "
            f"Draft review {state.get('review_status', 'unknown')}. "
            f"Test execution {'passed' if results.get('passed', False) else 'requires review'} "
            f"after {results.get('executed', 0)} generated test(s) "
            f"and {int(state.get('repair_attempts', 0))} repair attempt(s). "
            f"Rapita {'executed' if rapita_results.get('executed') else 'skipped'}."
        ),
        review_status=state.get("review_status", ""),
        review_notes=state.get("review_notes", ""),
        mappings=[MappingRow(**row) for row in state.get("mappings", [])],
        dd_rows=[DDRow(**row) for row in state.get("dd_rows", [])],
        discovered_files=[DiscoveredFile(**item) for item in state.get("discovered_files", [])],
        coverage=[CoverageItem(**row) for row in state.get("coverage", [])],
        test_results=results,
        artifacts=state.get("artifacts", {}),
        rapita_plan=state.get("rapita_plan", []),
        rapita_results=state.get("rapita_results", {}),
        failure_classification=state.get("failure_classification", []),
        suggested_fix_report=state.get("suggested_fix_report", ""),
        assumptions=state.get("assumptions", []),
        unresolved=state.get("unresolved", []),
        manual_review=state.get("manual_review", []),
    )
    report.conclusion = (
        f"Verification completed in {report.mode} mode for requirement {report.requirement_id or report.requirement_name}. "
        f"Review status: {report.review_status or 'unknown'}. "
        f"Generated {len(report.dd_rows)} DD rows, {len(report.mappings)} mappings, "
        f"{len(report.coverage)} coverage items, and "
        f"{report.test_results.get('executed', 0)} executed generated test(s) with "
        f"{int(state.get('repair_attempts', 0))} repair attempt(s). "
        f"Rapita {'executed' if rapita_results.get('executed') else 'skipped'}."
    )
    state["proof_report"] = report.to_dict()
    state.setdefault("logs", []).append("Proof report created.")
    return state


def learn(state: VerificationState, output_dir: Path) -> VerificationState:
    """Record the run outcome as reusable learning memory."""

    return learn_from_run(state, output_dir)


def write_outputs(state: VerificationState, output_dir: Path) -> VerificationState:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = dict(state.get("artifacts", {}))
    if state.get("data_dictionary_text"):
        path = output_dir / "Data_dictionary.csv"
        path.write_text(state["data_dictionary_text"])
        artifacts["Data_dictionary.csv"] = str(path)
    if state.get("uut_dictionary_text"):
        path = output_dir / "uut_dictionary.csv"
        path.write_text(state["uut_dictionary_text"])
        artifacts["uut_dictionary.csv"] = str(path)
    if state.get("rvstest_text"):
        path = output_dir / "verification.rvstest"
        path.write_text(state["rvstest_text"])
        artifacts["verification.rvstest"] = str(path)
    if state.get("python_test_text"):
        path = output_dir / "test_requirement_generated.py"
        path.write_text(state["python_test_text"])
        artifacts["test_requirement_generated.py"] = str(path)
    if state.get("traceability_notes_text"):
        path = output_dir / "traceability_notes.md"
        path.write_text(state["traceability_notes_text"])
        artifacts["traceability_notes.md"] = str(path)
    if state.get("rapita_config_text"):
        path = output_dir / "rapita" / "rvsconfig.xml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(state["rapita_config_text"])
        artifacts["rapita/rvsconfig.xml"] = str(path)
    if state.get("rapita_node_mapping_text"):
        path = output_dir / "rapita" / "rapita-node-mapping.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(state["rapita_node_mapping_text"])
        artifacts["rapita/rapita-node-mapping.md"] = str(path)
    if state.get("proof_report"):
        path = output_dir / "proof_report.md"
        artifacts["proof_report.md"] = str(path)
        state["artifacts"] = artifacts
        report = _proof_from_state(state)
        report.artifacts = artifacts
        path.write_text(render_proof_markdown(report))
    state["artifacts"] = artifacts
    state.setdefault("logs", []).append(f"Artifacts written to {output_dir}.")
    return state


def _files_from_state(state: VerificationState) -> list[Any]:
    return [DiscoveredFile(**item) for item in state.get("discovered_files", [])]


def _proof_from_state(state: VerificationState) -> ProofReport:
    return ProofReport(
        requirement_id=state.get("proof_report", {}).get("requirement_id", state.get("requirement_identifier", "")),
        requirement_name=state.get("proof_report", {}).get("requirement_name", state.get("requirement_name", state.get("requirement_identifier", ""))),
        mode=state.get("proof_report", {}).get("mode", state.get("mode", "Direct")),
        summary=state.get("proof_report", {}).get("summary", ""),
        mappings=[MappingRow(**row) for row in state.get("mappings", [])],
        dd_rows=[DDRow(**row) for row in state.get("dd_rows", [])],
        discovered_files=[DiscoveredFile(**item) for item in state.get("discovered_files", [])],
        coverage=[CoverageItem(**row) for row in state.get("coverage", [])],
        test_results=state.get("test_results", {}),
        artifacts=state.get("artifacts", {}),
        rapita_plan=state.get("rapita_plan", []),
        rapita_results=state.get("rapita_results", {}),
        assumptions=state.get("assumptions", []),
        unresolved=state.get("unresolved", []),
        manual_review=state.get("manual_review", []),
        conclusion=state.get("proof_report", {}).get("conclusion", ""),
    )


def load_model(config: AppConfig) -> ModelAdapter:
    return get_model(config)


def _derive_function_name(identifier: str, text: str, snippet: str) -> str:
    for candidate in _extract_function_candidates(snippet):
        return candidate
    for candidate in _extract_function_candidates(text):
        return candidate
    if identifier and identifier.lower().startswith("faf-"):
        return identifier
    return identifier or "VerificationComponent"


def _extract_function_candidates(text: str) -> list[str]:
    return [match.strip().rstrip("(").strip() for match in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\s*\(", text)]


def _extract_requirement_name(text: str) -> str:
    match = re.search(r"(?ims)^\s*#+\s*Name\s*$\s*(.+)$", text)
    if match:
        return match.group(1).strip()
    match = re.search(r"(?ims)^Name\s*$\s*(.+)$", text)
    if match:
        return match.group(1).strip()
    return ""


def _select_harness_component(state: VerificationState, fallback: str) -> str:
    for item in state.get("discovered_files", []):
        path = item.get("path", "")
        if item.get("kind") == "harness" and path:
            return path
    return fallback


def _derive_return_type(snippet: str) -> str:
    match = re.search(
        r"\b(void|bool|_Bool|int|uint32_t|uint16_t|uint8_t|float|double|[A-Za-z_][A-Za-z0-9_]*)\s+[A-Za-z_][A-Za-z0-9_]*\s*\(",
        snippet,
    )
    if match:
        return match.group(1)
    return "void"
