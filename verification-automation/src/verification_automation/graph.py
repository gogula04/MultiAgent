"""Optional LangGraph wiring for the verification workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .agents import (
    analyze_coverage,
    build_dd,
    build_proof,
    build_setup_and_tests,
    discover_repository,
    intake_requirement,
    learn,
    load_model,
    map_source_and_dictionaries,
    parse_requirement,
    resolve_requirement_state,
    review_drafts,
    select_strategy,
    write_outputs,
)
from .config import AppConfig
from .execution import execute_generated_tests
from .rapita import run_rapita_pipeline
from .triage import triage_failures


def build_graph(config: AppConfig):
    """Build the LangGraph workflow if the dependency is installed.

    Returns None when LangGraph is not available, so the local sequential
    orchestrator can be used as a fallback.
    """

    try:
        from langgraph.graph import StateGraph, END
    except Exception:
        return None

    from .state import VerificationState

    model = load_model(config)
    graph = StateGraph(VerificationState)

    graph.add_node("intake", intake_requirement)
    graph.add_node("resolve", lambda state: resolve_requirement_state(state, config))
    graph.add_node("discover", lambda state: discover_repository(state, config))
    graph.add_node("parse", lambda state: parse_requirement(state, model))
    graph.add_node("map", lambda state: map_source_and_dictionaries(state, model))
    graph.add_node("strategy", lambda state: select_strategy(state, model))
    graph.add_node("dd", lambda state: build_dd(state, model))
    graph.add_node("direct_builder", lambda state: build_setup_and_tests(state, config))
    graph.add_node("hybrid_builder", lambda state: build_setup_and_tests(state, config))
    graph.add_node("manual_builder", lambda state: build_setup_and_tests(state, config))
    graph.add_node("write_artifacts", lambda state: write_outputs(state, Path(state.get("output_dir", "artifacts"))))
    graph.add_node("review", lambda state: review_drafts(state, model, config))
    graph.add_node("execute", lambda state: execute_generated_tests(state, Path(state.get("output_dir", "artifacts"))))
    graph.add_node("rapita", lambda state: run_rapita_pipeline(state, config, Path(state.get("output_dir", "artifacts"))))
    graph.add_node("coverage", lambda state: analyze_coverage(state, model))
    graph.add_node("triage", lambda state: triage_failures(state, Path(state.get("output_dir", "artifacts"))))
    graph.add_node("learn", lambda state: learn(state, Path(state.get("output_dir", "artifacts"))))
    graph.add_node("proof", lambda state: build_proof(state, model))
    graph.add_node("write_report", lambda state: write_outputs(state, Path(state.get("output_dir", "artifacts"))))

    graph.set_entry_point("intake")
    graph.add_edge("intake", "resolve")
    def resolve_route(state: dict) -> str:
        return "blocked" if state.get("status") == "blocked" else "discover"

    graph.add_node("blocked", lambda state: state)
    graph.add_edge("blocked", "learn")
    def discover_route(state: dict) -> str:
        return "blocked" if state.get("status") == "blocked" else "parse"

    graph.add_conditional_edges(
        "resolve",
        resolve_route,
        {
            "discover": "discover",
            "blocked": "blocked",
        },
    )
    graph.add_conditional_edges(
        "discover",
        discover_route,
        {
            "parse": "parse",
            "blocked": "blocked",
        },
    )
    graph.add_edge("parse", "map")
    graph.add_edge("map", "strategy")
    graph.add_edge("strategy", "dd")
    def choose_mode(state: dict) -> str:
        mode = state.get("mode", "Direct")
        if mode == "Hybrid":
            return "hybrid_builder"
        if mode == "Manual":
            return "manual_builder"
        return "direct_builder"

    def dd_route(state: dict) -> str:
        return "blocked" if not state.get("dd_rows") else choose_mode(state)

    graph.add_conditional_edges(
        "dd",
        dd_route,
        {
            "blocked": "blocked",
            "direct_builder": "direct_builder",
            "hybrid_builder": "hybrid_builder",
            "manual_builder": "manual_builder",
        },
    )
    graph.add_edge("direct_builder", "write_artifacts")
    graph.add_edge("hybrid_builder", "write_artifacts")
    graph.add_edge("manual_builder", "write_artifacts")
    graph.add_edge("write_artifacts", "review")
    graph.add_edge("execute", "rapita")
    graph.add_edge("rapita", "coverage")

    def coverage_route(state: dict) -> str:
        results = state.get("test_results", {})
        if results.get("passed", False):
            return "proof"
        if int(state.get("repair_attempts", 0)) >= 1:
            return "proof"
        return "triage"

    def review_route(state: dict) -> str:
        return "execute" if state.get("review_status") == "approved" else "dd"

    graph.add_conditional_edges(
        "review",
        review_route,
        {
            "execute": "execute",
            "dd": "dd",
        },
    )
    graph.add_conditional_edges(
        "coverage",
        coverage_route,
        {
            "proof": "proof",
            "triage": "triage",
        },
    )
    graph.add_conditional_edges("triage", choose_mode, {
        "direct_builder": "direct_builder",
        "hybrid_builder": "hybrid_builder",
        "manual_builder": "manual_builder",
    })
    graph.add_edge("proof", "learn")
    graph.add_edge("learn", "write_report")
    graph.add_edge("write_report", END)

    return graph.compile()
