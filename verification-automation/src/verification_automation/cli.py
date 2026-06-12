"""Command-line entry point."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from pprint import pprint

from .config import AppConfig
from .graph import build_graph
from .orchestrator import VerificationOrchestrator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the verification automation workflow.")
    parser.add_argument("requirement", help="Requirement name or ID.")
    parser.add_argument("--text", default="", help="Requirement text.")
    parser.add_argument("--snippet", default="", help="Source snippet.")
    parser.add_argument("--repo-root", default=".", help="Repository root to scan.")
    parser.add_argument("--output-dir", default="artifacts", help="Directory for generated artifacts.")
    parser.add_argument(
        "--mode",
        default="Auto",
        choices=["Auto", "Direct", "Hybrid", "Manual"],
        help="Verification mode override.",
    )
    parser.add_argument("--use-graph", action="store_true", help="Use LangGraph when installed.")
    parser.add_argument(
        "--require-review",
        action="store_true",
        help="Pause after draft generation and leave the review gate pending instead of auto-approving locally.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = AppConfig.load(Path(args.repo_root))
    if args.require_review:
        config = replace(config, auto_approve=False)
    orchestrator = VerificationOrchestrator(config=config)
    output_dir = Path(args.output_dir)

    if args.use_graph:
        graph = build_graph(config)
        if graph is not None:
            result = graph.invoke(
                {
                    "requirement_identifier": args.requirement,
                    "requirement_name": "",
                    "requirement_text": args.text,
                    "source_snippet": args.snippet,
                    "related_requirements": [],
                    "logs": [],
                    "assumptions": [],
                    "unresolved": [],
                    "manual_review": [],
                    "rapita_plan": [],
                    "rapita_results": {},
                    "output_dir": str(output_dir),
                    "mode_override": args.mode,
                }
            )
        else:
            result = orchestrator.run_to_directory(args.requirement, args.text, args.snippet, output_dir, mode_override=args.mode)
    else:
        result = orchestrator.run_to_directory(args.requirement, args.text, args.snippet, output_dir, mode_override=args.mode)

    pprint(
        {
            "requirement": result.get("requirement_identifier"),
            "mode": result.get("mode"),
            "resolution": result.get("requirement_resolution_status"),
            "artifacts": {
                "Data_dictionary.csv": bool(result.get("data_dictionary_text")),
                "uut_dictionary.csv": bool(result.get("uut_dictionary_text")),
                "verification.rvstest": bool(result.get("rvstest_text")),
                "test_requirement_generated.py": bool(result.get("python_test_text")),
                "traceability_notes.md": bool(result.get("traceability_notes_text")),
                "rapita/rvsconfig.xml": bool(result.get("rapita_config_text")),
                "rapita/rapita-node-mapping.md": bool(result.get("rapita_node_mapping_text")),
                "proof_report.md": bool(result.get("proof_report")),
            },
            "review": {
                "status": result.get("review_status"),
                "notes": result.get("review_notes"),
            },
            "rapita": result.get("rapita_results", {}),
            "logs": result.get("logs", []),
        }
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
