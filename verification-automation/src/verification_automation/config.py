"""Configuration helpers for verification automation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    repo_root: Path
    poolside_base_url: str | None
    poolside_api_key: str | None
    poolside_model: str
    use_langchain: bool
    auto_approve: bool
    rapita_project: Path | None
    rapita_driver: str
    rapita_utconverter: str
    rapita_integration: str
    rapita_results_dir: Path | None
    rapita_enabled: bool

    @classmethod
    def load(cls, repo_root: Path | None = None) -> "AppConfig":
        root = repo_root or Path.cwd()
        return cls(
            repo_root=root,
            poolside_base_url=os.environ.get("POOLSIDE_BASE_URL"),
            poolside_api_key=os.environ.get("POOLSIDE_API_KEY"),
            poolside_model=os.environ.get("POOLSIDE_MODEL", "edx-malibu-model-2-1"),
            use_langchain=os.environ.get("VERIFICATION_USE_LANGCHAIN", "1") not in {"0", "false", "False"},
            auto_approve=os.environ.get("VERIFICATION_AUTO_APPROVE", "1") not in {"0", "false", "False"},
            rapita_project=Path(os.environ["RAPITA_PROJECT"]).expanduser() if os.environ.get("RAPITA_PROJECT") else None,
            rapita_driver=os.environ.get("RAPITA_DRIVER", "/usr/local/rvs/bin/rvsdriver"),
            rapita_utconverter=os.environ.get("RAPITA_UTCONVERTER", "/usr/local/rvs/bin/utconverter"),
            rapita_integration=os.environ.get("RAPITA_INTEGRATION", "linux-code_coverage"),
            rapita_results_dir=Path(os.environ["RAPITA_RESULTS_DIR"]).expanduser() if os.environ.get("RAPITA_RESULTS_DIR") else None,
            rapita_enabled=os.environ.get("RAPITA_ENABLED", "0") not in {"0", "false", "False"},
        )
