"""Failure triage and self-healing support."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .state import VerificationState


def triage_failures(state: VerificationState, output_dir: Path) -> VerificationState:
    results = state.get("test_results", {})
    details = results.get("details", [])
    failed = [item for item in details if item.get("status") == "failed"]

    if not failed:
        state.setdefault("logs", []).append("No failures detected; self-healing not required.")
        return state

    classification = []
    notes = []
    for failure in failed:
        name = failure.get("name", "unknown")
        detail = failure.get("detail", "")
        category, suggestion = classify_failure(name, detail, state)
        note = f"{name}: {detail}"
        notes.append(note)
        classification.append(
            {
                "test": name,
                "detail": detail,
                "category": category,
                "suggestion": suggestion,
            }
        )

    state.setdefault("unresolved", []).extend(notes)
    state.setdefault("manual_review", []).append("Review failed generated tests and adjust DD/harness/test generation accordingly.")
    state.setdefault("logs", []).append(f"Failure triage identified {len(failed)} failing generated test(s).")
    state["failure_classification"] = classification
    state["suggested_fix_report"] = _render_suggested_fix_report(classification)

    # Minimal self-healing action for the scaffold:
    # keep the artifacts but mark the workflow for a targeted retry if the
    # caller wants to re-run with corrected repository data.
    state["status"] = "repair_needed"
    state["repair_attempts"] = int(state.get("repair_attempts", 0)) + 1
    return state


def classify_failure(test_name: str, detail: str, state: VerificationState) -> tuple[str, str]:
    text = f"{test_name} {detail}".lower()
    if any(term in text for term in ("py_compile", "syntax", "import", "missing generated", "module")):
        return "Test Setup Issue", "Fix generated test syntax/imports or missing output files."
    if any(term in text for term in ("dd_", "verificationidentifier", "mapping", "trace")):
        return "DD Mapping Issue", "Review requirement-to-DD naming and traceability mappings."
    if any(term in text for term in ("rvstest", "harness", "vector", "stub", "localdecls")):
        return "Harness Issue", "Review RVSTest/harness generation and stub wiring."
    if any(term in text for term in ("ambigu", "conflict", "unclear", "contradict")):
        return "Requirement Ambiguity", "Clarify the requirement wording and acceptance criteria."
    if state.get("coverage", []) and not state.get("test_results", {}).get("passed", False):
        return "Source Defect", "Investigate the implementation against the verified requirement path."
    return "Source Defect", "Inspect source logic and generated checks for the failing path."


def _render_suggested_fix_report(classification: list[dict[str, str]]) -> str:
    if not classification:
        return "No failures classified."
    lines = ["# Suggested Fix Report", ""]
    for item in classification:
        lines.append(f"- {item['test']}: {item['category']} -> {item['suggestion']}")
    return "\n".join(lines) + "\n"
