"""Requirement resolution helpers for repo-backed verification runs."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import re
from pathlib import Path
from typing import Any


REQUIREMENT_SUFFIXES = {".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".xml"}
IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".mypy_cache", ".pytest_cache", "artifacts", "out", "dist", "build"}
REQUIREMENT_ROOTS = ("requirements/HLR", "requirements/LLR")


@dataclass(slots=True)
class ResolvedRequirement:
    found: bool
    identifier: str
    name: str = ""
    text: str = ""
    file_path: str = ""
    excerpt: str = ""
    bold_terms: list[str] = None  # type: ignore[assignment]
    matched_lines: list[str] = None  # type: ignore[assignment]
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["bold_terms"] = list(self.bold_terms or [])
        payload["matched_lines"] = list(self.matched_lines or [])
        return payload


def resolve_requirement(repo_root: Path, identifier: str, requirement_text: str = "", source_snippet: str = "") -> ResolvedRequirement:
    identifier = identifier.strip()
    requirement_text = requirement_text.strip()
    source_snippet = source_snippet.strip()

    if requirement_text:
        text = requirement_text
        return ResolvedRequirement(
            found=True,
            identifier=identifier or _infer_identifier(requirement_text) or "UNSPECIFIED",
            name=_extract_name(requirement_text) or identifier,
            text=requirement_text,
            excerpt=_first_lines(requirement_text),
            bold_terms=_extract_bold_terms(requirement_text),
            matched_lines=[line.strip() for line in requirement_text.splitlines()[:12] if line.strip()],
            notes="Using provided requirement text.",
        )

    if not identifier:
        return ResolvedRequirement(found=False, identifier="UNSPECIFIED", notes="Requirement identifier was empty.")

    best = _find_best_requirement_file(repo_root, identifier)
    if best is None:
        return ResolvedRequirement(
            found=False,
            identifier=identifier,
            text="",
            excerpt="",
            bold_terms=[],
            matched_lines=[],
            notes=f"Requirement '{identifier}' was not found in the repo requirement folders.",
        )

    text = best.read_text(errors="ignore")
    name = _extract_name(text) or _infer_name_from_path(best)
    bold_terms = _extract_bold_terms(text)
    matched_lines = _matched_lines(text, identifier)
    excerpt = _excerpt_around_match(text, identifier)
    if source_snippet:
        matched_lines = _merge_unique(matched_lines, [source_snippet.strip()])
    return ResolvedRequirement(
        found=True,
        identifier=identifier,
        name=name,
        text=text,
        file_path=str(best),
        excerpt=excerpt,
        bold_terms=bold_terms,
        matched_lines=matched_lines,
        notes=f"Resolved from requirement file: {best.relative_to(repo_root).as_posix()}",
    )


def _find_best_requirement_file(repo_root: Path, identifier: str) -> Path | None:
    roots = [repo_root / root for root in REQUIREMENT_ROOTS]
    needle = identifier.strip().lower()
    candidates: list[tuple[float, Path]] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in IGNORED_DIRS or part.startswith("artifacts") for part in path.parts):
                continue
            if path.suffix.lower() not in REQUIREMENT_SUFFIXES:
                continue
            score = 0.0
            rel = path.as_posix().lower()
            if needle in rel:
                score += 4.0
            try:
                text = path.read_text(errors="ignore").lower()
            except Exception:
                continue
            if needle in text:
                score += 5.0
            if "### name" in text and "### item id" in text:
                score += 2.0
            if score > 0.0:
                candidates.append((score, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], len(item[1].as_posix())), reverse=True)
    return candidates[0][1]


def _extract_name(text: str) -> str:
    patterns = [
        r"(?im)^\s*###\s*Name\s*$\s*(.+?)(?=^\s*###\s|\Z)",
        r"(?im)^\s*Name\s*$\s*(.+?)(?=^\s*[A-Z][A-Za-z ]+\s*$|\Z)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.S | re.M)
        if match:
            return match.group(1).strip().splitlines()[0].strip()
    return ""


def _infer_identifier(text: str) -> str:
    match = re.search(r"FAF-[A-Z]+-\d+", text)
    return match.group(0) if match else ""


def _infer_name_from_path(path: Path) -> str:
    stem = path.stem.replace("_", " ").replace("-", " ").strip()
    return stem.title()


def _extract_bold_terms(text: str) -> list[str]:
    terms = []
    seen: set[str] = set()
    for match in re.findall(r"\*\*(.+?)\*\*", text):
        term = " ".join(match.split()).strip(" .,:;()[]{}<>")
        if len(term) < 2:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append(term)
    return terms


def _matched_lines(text: str, identifier: str) -> list[str]:
    needle = identifier.lower()
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if needle in line.lower():
            lines.append(line)
    return lines[:12]


def _excerpt_around_match(text: str, identifier: str, context_lines: int = 4) -> str:
    lines = text.splitlines()
    needle = identifier.lower()
    for index, raw in enumerate(lines):
        if needle in raw.lower():
            start = max(0, index - context_lines)
            end = min(len(lines), index + context_lines + 1)
            return "\n".join(line.rstrip() for line in lines[start:end]).strip()
    return _first_lines(text, limit=12)


def _first_lines(text: str, limit: int = 8) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[:limit]).strip()


def _merge_unique(first: list[str], second: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in [*first, *second]:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
