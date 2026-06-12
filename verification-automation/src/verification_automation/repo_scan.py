"""Repository discovery helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import DiscoveredFile


SOURCE_EXTENSIONS = {".c", ".cc", ".cpp", ".h", ".hpp", ".py", ".cs", ".java", ".js", ".ts"}
DICT_EXTENSIONS = {".csv", ".tsv", ".yaml", ".yml", ".json", ".xml", ".txt", ".md"}
TEST_HINTS = ("test", "spec", "verify", "rvstest", "rvs")
IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".mypy_cache", ".pytest_cache", "artifacts", "out", "dist", "build"}


@dataclass(slots=True)
class RepoDiscovery:
    requirement_files: list[DiscoveredFile]
    source_files: list[DiscoveredFile]
    dictionary_files: list[DiscoveredFile]
    test_files: list[DiscoveredFile]
    harness_files: list[DiscoveredFile]
    closest_examples: list[DiscoveredFile]


def _file_kind(path: Path) -> str:
    name = path.name.lower()
    parts = [part.lower() for part in path.parts]
    suffix = path.suffix.lower()
    if "requirements" in parts and ("hlr" in parts or "llr" in parts):
        return "requirement"
    if "requirements" in parts and "data_dictionary" in parts:
        return "dictionary"
    if "verification" in parts and "test-cases" in parts:
        return "test"
    if "verification" in parts and ("test-procedures" in parts or "procedure-vectors" in parts):
        return "harness"
    if "software" in parts and "source" in parts:
        return "source"
    if "requirement" in name or "req" in name or "trace" in name:
        return "requirement"
    if "rvstest" in name or name.endswith(".rvs") or "harness" in name:
        return "harness"
    if any(token in name for token in TEST_HINTS):
        return "test"
    if suffix in SOURCE_EXTENSIONS:
        return "source"
    if suffix in DICT_EXTENSIONS:
        return "dictionary"
    return "other"


def scan_repository(repo_root: Path, keywords: list[str] | None = None, limit: int = 200) -> RepoDiscovery:
    keywords = [k.lower() for k in (keywords or []) if k.strip()]
    requirement_files: list[DiscoveredFile] = []
    source_files: list[DiscoveredFile] = []
    dictionary_files: list[DiscoveredFile] = []
    test_files: list[DiscoveredFile] = []
    harness_files: list[DiscoveredFile] = []
    closest_examples: list[DiscoveredFile] = []

    for path in sorted(repo_root.rglob("*")):
        if len(closest_examples) >= limit:
            break
        if not path.is_file():
            continue
        if any(part in IGNORED_DIRS or part.startswith("artifacts") for part in path.parts):
            continue

        kind = _file_kind(path)
        rel = path.relative_to(repo_root).as_posix()
        relevance = _keyword_score(rel, keywords)
        item = DiscoveredFile(path=rel, kind=kind, relevance=relevance, notes="")

        if kind == "requirement":
            requirement_files.append(item)
        elif kind == "source":
            source_files.append(item)
        elif kind == "dictionary":
            dictionary_files.append(item)
        elif kind == "test":
            test_files.append(item)
        elif kind == "harness":
            harness_files.append(item)

        if relevance > 0:
            closest_examples.append(item)

    closest_examples.sort(key=lambda x: x.relevance, reverse=True)
    return RepoDiscovery(
        requirement_files=requirement_files,
        source_files=source_files,
        dictionary_files=dictionary_files,
        test_files=test_files,
        harness_files=harness_files,
        closest_examples=closest_examples[:10],
    )


def _keyword_score(text: str, keywords: list[str]) -> float:
    if not keywords:
        return 0.0
    score = 0.0
    lowered = text.lower()
    for kw in keywords:
        if kw in lowered:
            score += 1.0
    return score / max(len(keywords), 1)
