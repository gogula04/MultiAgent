"""Helpers for canonical Rapita configuration assets."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from .config import AppConfig


def render_rvsconfig_xml() -> str:
    return resources.files("verification_automation.resources.rapita").joinpath("rvsconfig.xml").read_text(encoding="utf-8")


def render_node_mapping(config: AppConfig, component_name: str) -> str:
    repo_root = config.repo_root.as_posix()
    lines = [
        "# Rapita XML to Multi-Agent Mapping",
        "",
        f"- Repository root: `{repo_root}`",
        f"- Component: `{component_name}`",
        f"- Project: `{config.rapita_project.name if config.rapita_project else 'unconfigured'}`",
        f"- Integration: `{config.rapita_integration}`",
        "",
        "This bundle mirrors the canonical reference in `docs/rapita-node-mapping.md`.",
        "",
        "| XML section | Multi-agent node | Notes |",
        "| --- | --- | --- |",
        "| `<project>` | Requirement Intake Agent / Repo Discovery Agent | Project identity and environment wiring. |",
        "| `<environment>` | Source + Dictionary Mapping Agent | Dictionary path, tests folder, and PATH setup. |",
        "| `<integration-recipes>` | Verification Strategy Agent / Direct-Hybrid-Manual Builder | Build-stage contract. |",
        "| `<integrations>` | Test Execution Agent / Coverage Analyzer Agent | Coverage collection and export strategy. |",
        "| `<analysis>` | Coverage Analyzer Agent | Coverage profile evidence. |",
        "| `<targets>` | Test Execution Agent / Failure Triage Agent | Build/run commands and instrumentation behavior. |",
        "| `<exports>` | Proof & Traceability Reporter | Export outputs for coverage and tests. |",
        "| `<testframework>` | Repo Discovery Agent / Harness Builder | Procedure folder location. |",
        "",
        "## Generated Paths",
        f"- `artifacts/rapita/rvsconfig.xml`",
        f"- `artifacts/rapita/rapita-node-mapping.md`",
        "",
        "## Repository Anchors",
        "- Requirements: `requirements/HLR` and `requirements/LLR`",
        "- Data dictionaries: `requirements/data_dictionary`",
        "- Source: `software/source`",
        "- Test cases: `verification/test-cases`",
        "- Procedures: `verification/test-procedures`",
    ]
    return "\n".join(lines) + "\n"


def materialize_rapita_assets(config: AppConfig, output_dir: Path, component_name: str) -> dict[str, str]:
    rapita_dir = output_dir / "rapita"
    rapita_dir.mkdir(parents=True, exist_ok=True)

    config_path = rapita_dir / "rvsconfig.xml"
    mapping_path = rapita_dir / "rapita-node-mapping.md"

    config_text = render_rvsconfig_xml()
    mapping_text = render_node_mapping(config, component_name)

    config_path.write_text(config_text)
    mapping_path.write_text(mapping_text)

    return {
        "rapita/rvsconfig.xml": str(config_path),
        "rapita/rapita-node-mapping.md": str(mapping_path),
    }
