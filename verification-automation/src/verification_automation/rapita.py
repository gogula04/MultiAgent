"""Rapita execution plan and optional runner."""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import AppConfig
from .rapita_assets import materialize_rapita_assets
from .state import VerificationState


@dataclass(slots=True)
class RapitaCommand:
    stage: str
    command: list[str]
    cwd: str


@dataclass(slots=True)
class RapitaResult:
    enabled: bool
    executed: bool
    success: bool
    commands: list[dict[str, Any]]
    logs: list[str]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_rapita_plan(config: AppConfig, output_dir: Path, component_name: str) -> list[RapitaCommand]:
    if not config.rapita_project:
        return []

    project = config.rapita_project
    results_dir = config.rapita_results_dir or (project.parent / "rvs_rapitest")
    results_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = output_dir / "rapita_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    rvstest_file = output_dir / "verification.rvstest"
    rts_name = f"{_slugify(component_name)}.rts"
    prepare_rvd = results_dir / "rapitest-prepare.rvd"

    commands = [
        RapitaCommand(
            stage="deploy",
            command=[config.rapita_driver, "--project", str(project), "--integration", config.rapita_integration, "--deploy-library"],
            cwd=str(project.parent),
        ),
        RapitaCommand(
            stage="prepare",
            command=[config.rapita_driver, "--project", str(project), "--integration", config.rapita_integration, "--clean", "--prepare"],
            cwd=str(project.parent),
        ),
    ]

    if rvstest_file.exists():
        commands.append(
            RapitaCommand(
                stage="convert",
                command=[
                    config.rapita_utconverter,
                    "-i",
                    str(rvstest_file),
                    "--output-format",
                    "RTS",
                    "-d",
                    str(tmp_dir),
                    "-o",
                    rts_name,
                    "--db",
                    str(prepare_rvd),
                ],
                cwd=str(output_dir),
            )
        )
        rts_file = tmp_dir / rts_name
        commands.extend(
            [
                RapitaCommand(
                    stage="build",
                    command=[config.rapita_driver, "--project", str(project), "--integration", config.rapita_integration, "--test", str(rts_file), "--build"],
                    cwd=str(project.parent),
                ),
                RapitaCommand(
                    stage="run",
                    command=[config.rapita_driver, "--project", str(project), "--integration", config.rapita_integration, "--run"],
                    cwd=str(project.parent),
                ),
                RapitaCommand(
                    stage="report",
                    command=[config.rapita_driver, "--project", str(project), "--integration", config.rapita_integration, "--report"],
                    cwd=str(project.parent),
                ),
                RapitaCommand(
                    stage="export",
                    command=[config.rapita_driver, "--project", str(project), "--integration", config.rapita_integration, "--export"],
                    cwd=str(project.parent),
                ),
            ]
        )
    return commands


def run_rapita_pipeline(state: VerificationState, config: AppConfig, output_dir: Path) -> VerificationState:
    component_name = state.get("component_name", state.get("requirement_identifier", "verification"))
    support_files = materialize_rapita_assets(config, output_dir, component_name)
    state.setdefault("artifacts", {}).update(support_files)
    plan = build_rapita_plan(config, output_dir, component_name)
    state["rapita_plan"] = [asdict(item) for item in plan]

    if not plan or not config.rapita_enabled:
        state["rapita_results"] = RapitaResult(
            enabled=bool(config.rapita_project),
            executed=False,
            success=False,
            commands=state["rapita_plan"],
            logs=["Rapita execution skipped (not enabled or not configured)."],
            summary="Rapita pipeline not executed on this machine.",
        ).to_dict()
        state["rapita_results"]["support_files"] = support_files
        state.setdefault("logs", []).append("Rapita pipeline skipped.")
        return state

    logs: list[str] = []
    command_dicts: list[dict[str, Any]] = []
    success = True
    for item in plan:
        command_dicts.append(asdict(item))
        try:
            result = subprocess.run(item.command, cwd=item.cwd, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            logs.append(f"{item.stage}: missing executable - {exc}")
            success = False
            break
        logs.append(f"{item.stage}: returncode={result.returncode}")
        if result.stdout:
            logs.append(result.stdout.strip())
        if result.stderr:
            logs.append(result.stderr.strip())
        if result.returncode != 0:
            success = False
            break

    state["rapita_results"] = RapitaResult(
        enabled=True,
        executed=True,
        success=success,
        commands=command_dicts,
        logs=logs,
        summary="Rapita pipeline executed." if success else "Rapita pipeline failed.",
    ).to_dict()
    state["rapita_results"]["support_files"] = support_files
    state.setdefault("logs", []).append(state["rapita_results"]["summary"])
    return state


def _slugify(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_") or "verification"
