"""Coverage analysis for generated verification artifacts."""

from __future__ import annotations

from dataclasses import asdict

from .models import CoverageItem, RequirementBehavior, RequirementInput
from .state import VerificationState


def analyze_verification_coverage(state: VerificationState) -> VerificationState:
    req = RequirementInput(
        identifier=state.get("requirement_identifier", ""),
        text=state.get("requirement_text", ""),
        source_snippet=state.get("source_snippet", ""),
    )
    behaviors = [RequirementBehavior(**row) for row in state.get("behaviors", [])]
    mode = state.get("mode", "Direct")
    results = state.get("test_results", {})
    rapita_results = state.get("rapita_results", {})
    passed = bool(results.get("passed"))

    items = [
        CoverageItem(item="Requirement trace coverage", status="covered" if state.get("mappings") else "partial", notes="Mappings generated."),
        CoverageItem(item="Artifact generation coverage", status="covered" if state.get("dd_rows") else "partial", notes="DD rows generated."),
        CoverageItem(item="Execution coverage", status="covered" if passed else "partial", notes=f"Executed {results.get('executed', 0)} generated test(s)."),
        CoverageItem(item="Rapita execution coverage", status="covered" if rapita_results.get("executed") else "partial", notes=rapita_results.get("summary", "Rapita pipeline not executed.")),
        CoverageItem(item="Behavior coverage", status="covered" if behaviors else "partial", notes=f"{len(behaviors)} behavior block(s) parsed."),
        CoverageItem(item="Boundary / robustness coverage", status="covered" if _has_behavior(behaviors, "Boundary") else "partial", notes="Boundary behavior inferred or absent."),
        CoverageItem(item="Fault / null coverage", status="covered" if _has_behavior(behaviors, "Fault") or _has_behavior(behaviors, "Null") else "partial", notes="Fault/null behavior inferred or absent."),
        CoverageItem(item="Branch / MC/DC coverage", status="covered" if mode != "Direct" else "partial", notes=f"Mode = {mode}."),
    ]

    state["coverage"] = [asdict(item) for item in items]
    state.setdefault("logs", []).append(f"Coverage analysis completed with {len(items)} item(s).")
    return state


def _has_behavior(behaviors: list[RequirementBehavior], needle: str) -> bool:
    return any(needle.lower() in b.label.lower() or needle.lower() in b.description.lower() for b in behaviors)
