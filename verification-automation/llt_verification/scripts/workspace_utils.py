"""Shared workspace helpers for the LLT verification skill."""

import os
from pathlib import Path
from typing import List, Optional, Tuple


def detect_workspace_root(start: Optional[str] = None) -> Path:
    """Resolve the workspace root from env, cwd, script location, or parents."""
    candidates = []
    env_root = os.environ.get("LLT_WORKSPACE_ROOT")
    if env_root:
        candidates.append(Path(env_root).expanduser())
    if start:
        candidates.append(Path(start).expanduser())
    candidates.append(Path.cwd())
    candidates.append(Path(__file__).resolve().parent.parent)

    markers = [
        ("requirements", "LLR"),
        ("verification", "test-procedures"),
        ("software", "source"),
        ("SKILL.md",),
    ]

    checked = set()
    for seed in candidates:
        for path in [seed, *seed.parents]:
            if path in checked:
                continue
            checked.add(path)
            for marker in markers:
                marker_path = path.joinpath(*marker)
                if marker_path.exists():
                    return path
    return Path.cwd()


def candidate_dirs(
    workspace_root: Path,
    relative_paths: List[Tuple[str, ...]],
    fallback_to_root: bool = True,
) -> List[Path]:
    """Return the existing candidate directories under a workspace root."""
    dirs = []
    for rel in relative_paths:
        candidate = workspace_root.joinpath(*rel)
        if candidate.exists():
            dirs.append(candidate)
    if not dirs and fallback_to_root:
        dirs.append(workspace_root)
    return dirs
