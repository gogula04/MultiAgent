"""Lightweight repo retrieval for evidence-first verification generation."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import math
import re
from pathlib import Path
from typing import Iterable

from .learning_store import LearningStore
from .models import RequirementInput, DiscoveredFile


TEXT_EXTENSIONS = {".c", ".cc", ".cpp", ".h", ".hpp", ".py", ".csv", ".tsv", ".yaml", ".yml", ".json", ".xml", ".txt", ".md", ".rvs", ".rvstest"}
IGNORED_DIRS = {".git", "__pycache__", ".venv", ".mypy_cache", ".pytest_cache", "node_modules", "artifacts", "out", "dist", "build"}


@dataclass(slots=True)
class RAGChunk:
    path: str
    kind: str
    text: str
    tokens: Counter[str]
    total_tokens: int
    source: str = "repo"


@dataclass(slots=True)
class RAGHit:
    path: str
    kind: str
    score: float
    excerpt: str
    reason: str
    source: str = "repo"


@dataclass(slots=True)
class EvidenceBundle:
    """Structured retrieval evidence used to gate generation."""

    query: str
    same_module_terms: list[str]
    hits: list[RAGHit]
    hit_counts: dict[str, int]
    same_function_hits: list[RAGHit]
    same_module_hits: list[RAGHit]
    has_requirement_evidence: bool
    has_source_evidence: bool
    has_dictionary_evidence: bool
    has_test_evidence: bool
    has_learning_example: bool
    supports_generation: bool
    confidence: float
    recommended_mode: str
    blocking_reason: str
    summary: str

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "same_module_terms": list(self.same_module_terms),
            "hits": [asdict(hit) for hit in self.hits],
            "hit_counts": dict(self.hit_counts),
            "same_function_hits": [asdict(hit) for hit in self.same_function_hits],
            "same_module_hits": [asdict(hit) for hit in self.same_module_hits],
            "has_requirement_evidence": self.has_requirement_evidence,
            "has_source_evidence": self.has_source_evidence,
            "has_dictionary_evidence": self.has_dictionary_evidence,
            "has_test_evidence": self.has_test_evidence,
            "has_learning_example": self.has_learning_example,
            "supports_generation": self.supports_generation,
            "confidence": self.confidence,
            "recommended_mode": self.recommended_mode,
            "blocking_reason": self.blocking_reason,
            "summary": self.summary,
        }


class RepoRAGIndex:
    """A deterministic retrieval index over repo text and learning examples."""

    def __init__(self, repo_root: Path, output_dir: Path | None = None):
        self.repo_root = repo_root
        self.output_dir = output_dir
        self.chunks: list[RAGChunk] = []

    @classmethod
    def build(cls, repo_root: Path, output_dir: Path | None = None) -> "RepoRAGIndex":
        index = cls(repo_root, output_dir)
        index.chunks = index._collect_chunks()
        return index

    def search(
        self,
        query: str,
        top_k: int = 8,
        same_module_terms: Iterable[str] | None = None,
    ) -> list[RAGHit]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        query_counts = Counter(query_tokens)
        same_module_terms = [term.lower() for term in (same_module_terms or []) if term]

        hits: list[RAGHit] = []
        for chunk in self.chunks:
            score = _cosine_similarity(query_counts, chunk.tokens)
            if score <= 0:
                continue
            lower_path = chunk.path.lower()
            lower_text = chunk.text.lower()
            if any(term and term in lower_path for term in same_module_terms):
                score += 0.2
            if any(term and term in lower_text for term in same_module_terms):
                score += 0.1
            if _looks_like_same_function(query_tokens, lower_path, lower_text):
                score += 0.35
            if chunk.kind in {"requirement", "dictionary"}:
                score += 0.05
            if chunk.source == "learning":
                score += 0.15
            excerpt = _make_excerpt(chunk.text, query_tokens)
            reason = _build_reason(query_tokens, chunk)
            hits.append(RAGHit(path=chunk.path, kind=chunk.kind, score=round(score, 4), excerpt=excerpt, reason=reason, source=chunk.source))

        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[:top_k]

    def profile(self, query: str, same_module_terms: Iterable[str] | None = None) -> dict[str, object]:
        hits = self.search(query, top_k=10, same_module_terms=same_module_terms)
        by_kind: dict[str, int] = {}
        for hit in hits:
            by_kind[hit.kind] = by_kind.get(hit.kind, 0) + 1
        return {
            "total_chunks": len(self.chunks),
            "top_hits": [hit.__dict__ for hit in hits],
            "hit_counts": by_kind,
            "has_requirement_evidence": any(hit.kind == "requirement" for hit in hits),
            "has_source_evidence": any(hit.kind == "source" for hit in hits),
            "has_dictionary_evidence": any(hit.kind == "dictionary" for hit in hits),
            "has_test_evidence": any(hit.kind in {"test", "harness"} for hit in hits),
        }

    def _collect_chunks(self) -> list[RAGChunk]:
        chunks: list[RAGChunk] = []
        for path in sorted(self.repo_root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in IGNORED_DIRS or part.startswith("artifacts") for part in path.parts):
                continue
            if path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            text = _safe_read(path)
            if not text.strip():
                continue
            rel = path.relative_to(self.repo_root).as_posix()
            kind = _infer_kind(rel)
            chunk_texts = _chunk_text(text)
            for idx, chunk_text in enumerate(chunk_texts):
                tokens = Counter(_tokenize(chunk_text))
                if not tokens:
                    continue
                chunk_path = rel if len(chunk_texts) == 1 else f"{rel}#chunk{idx + 1}"
                chunks.append(RAGChunk(path=chunk_path, kind=kind, text=chunk_text, tokens=tokens, total_tokens=sum(tokens.values())))

        if self.output_dir is not None:
            learning_dir = self.output_dir / "learning"
            if learning_dir.exists():
                store = LearningStore(learning_dir)
                chunks.extend(_learning_chunks(store))
        return chunks


def build_evidence_bundle(
    repo_root: Path,
    requirement: RequirementInput,
    discovered_files: list[DiscoveredFile],
    resolved_requirement: dict[str, object] | None = None,
    output_dir: Path | None = None,
) -> EvidenceBundle:
    index = RepoRAGIndex.build(repo_root, output_dir)
    query = _build_query(requirement, resolved_requirement)
    same_module_terms = _same_module_terms(requirement, discovered_files, resolved_requirement)
    hits = index.search(query, top_k=12, same_module_terms=same_module_terms)
    hit_counts: dict[str, int] = {}
    for hit in hits:
        hit_counts[hit.kind] = hit_counts.get(hit.kind, 0) + 1

    same_function_hits = [hit for hit in hits if _same_function_match(hit, requirement, resolved_requirement)]
    same_module_hits = [hit for hit in hits if _same_module_match(hit, same_module_terms)]
    has_requirement_evidence = any(hit.kind == "requirement" for hit in hits)
    has_source_evidence = any(hit.kind == "source" for hit in hits)
    has_dictionary_evidence = any(hit.kind == "dictionary" for hit in hits)
    has_test_evidence = any(hit.kind in {"test", "harness"} for hit in hits)
    has_learning_example = any(hit.source == "learning" for hit in hits)
    has_example_evidence = has_test_evidence or has_learning_example
    has_same_example = bool(same_function_hits or same_module_hits)

    confidence = _confidence_score(
        has_requirement_evidence=has_requirement_evidence,
        has_source_evidence=has_source_evidence,
        has_dictionary_evidence=has_dictionary_evidence,
        has_example_evidence=has_example_evidence,
        has_same_example=has_same_example,
        hits=hits,
    )
    supports_generation = (
        has_requirement_evidence
        and has_source_evidence
        and has_dictionary_evidence
        and has_example_evidence
        and has_same_example
        and confidence >= 0.6
    )
    recommended_mode = _recommend_mode(hits, same_module_hits, requirement)
    blocking_reason = ""
    if not supports_generation:
        missing: list[str] = []
        if not has_requirement_evidence:
            missing.append("requirement evidence")
        if not has_source_evidence:
            missing.append("source evidence")
        if not has_dictionary_evidence:
            missing.append("dictionary evidence")
        if not has_example_evidence:
            missing.append("verified DD/RVSTest/Python example")
        if not has_same_example:
            missing.append("same-function or same-module example")
        if confidence < 0.6:
            missing.append("retrieval confidence")
        blocking_reason = (
            f"Insufficient repository evidence for {requirement.identifier or 'UNSPECIFIED'}: "
            + ", ".join(missing)
            + "."
        )

    summary = _evidence_summary(hits, recommended_mode)
    return EvidenceBundle(
        query=query,
        same_module_terms=same_module_terms,
        hits=hits,
        hit_counts=hit_counts,
        same_function_hits=same_function_hits,
        same_module_hits=same_module_hits,
        has_requirement_evidence=has_requirement_evidence,
        has_source_evidence=has_source_evidence,
        has_dictionary_evidence=has_dictionary_evidence,
        has_test_evidence=has_test_evidence,
        has_learning_example=has_learning_example,
        supports_generation=supports_generation,
        confidence=round(confidence, 3),
        recommended_mode=recommended_mode,
        blocking_reason=blocking_reason,
        summary=summary,
    )


def _learning_chunks(store: LearningStore) -> list[RAGChunk]:
    chunks: list[RAGChunk] = []
    for source_path, kind in [
        (store.gold_examples_path, "learning"),
        (store.failure_examples_path, "learning"),
        (store.run_history_path, "learning"),
        (store.learning_summary_path, "learning"),
    ]:
        if not source_path.exists():
            continue
        text = _safe_read(source_path)
        if not text.strip():
            continue
        for idx, chunk_text in enumerate(_chunk_text(text)):
            tokens = Counter(_tokenize(chunk_text))
            if not tokens:
                continue
            chunk_path = f"{source_path.relative_to(store.root_dir.parent).as_posix()}#chunk{idx + 1}"
            chunks.append(RAGChunk(path=chunk_path, kind=kind, text=chunk_text, tokens=tokens, total_tokens=sum(tokens.values()), source="learning"))
    return chunks


def _infer_kind(rel_path: str) -> str:
    lower = rel_path.lower()
    parts = lower.split("/")
    name = Path(rel_path).name.lower()
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
    if "trace" in name or "requirement" in name:
        return "requirement"
    if name.endswith(".rvstest") or name.endswith(".rvs") or "harness" in name:
        return "harness"
    if name.endswith(".csv") or name.endswith(".json") or name.endswith(".xml") or name.endswith(".yaml") or name.endswith(".yml"):
        return "dictionary"
    if name.endswith(".py") and ("test" in name or "verify" in name):
        return "test"
    if name.endswith((".c", ".cpp", ".h", ".hpp")):
        return "source"
    return "other"


def _chunk_text(text: str, max_chars: int = 1600) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines():
        line = line.rstrip()
        if not line and current:
            block = "\n".join(current).strip()
            if block:
                blocks.append(block)
            current = []
            current_len = 0
            continue
        if current_len + len(line) > max_chars and current:
            block = "\n".join(current).strip()
            if block:
                blocks.append(block)
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += len(line)
    if current:
        block = "\n".join(current).strip()
        if block:
            blocks.append(block)
    return blocks or [text.strip()]


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)]


def _cosine_similarity(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[token] * b[token] for token in common)
    if dot <= 0:
        return 0.0
    norm_a = math.sqrt(sum(count * count for count in a.values()))
    norm_b = math.sqrt(sum(count * count for count in b.values()))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


def _looks_like_same_function(query_tokens: list[str], path: str, text: str) -> bool:
    joined = f"{path} {text}"
    return any(token in joined for token in query_tokens if len(token) > 4)


def _make_excerpt(text: str, query_tokens: list[str], width: int = 240) -> str:
    lower = text.lower()
    positions = [lower.find(token.lower()) for token in query_tokens if lower.find(token.lower()) >= 0]
    if positions:
        pos = min(positions)
        start = max(0, pos - width // 2)
        end = min(len(text), start + width)
        return " ".join(text[start:end].split())
    return " ".join(text[:width].split())


def _build_reason(query_tokens: list[str], chunk: RAGChunk) -> str:
    hits = [token for token in query_tokens if token in chunk.tokens]
    if chunk.source == "learning":
        return f"Learning example matched on {', '.join(hits[:4]) or 'repo memory'}."
    return f"Repo chunk matched on {', '.join(hits[:4]) or 'keyword overlap'}."


def _build_query(requirement: RequirementInput, resolved_requirement: dict[str, object] | None) -> str:
    parts: list[str] = [
        requirement.identifier,
        requirement.text,
        requirement.source_snippet,
    ]
    if resolved_requirement:
        parts.extend(
            [
                str(resolved_requirement.get("name", "")),
                str(resolved_requirement.get("excerpt", "")),
                " ".join(resolved_requirement.get("bold_terms", []) or []),
                " ".join(resolved_requirement.get("matched_lines", []) or []),
            ]
        )
    return " ".join(part for part in parts if part).strip()


def _same_module_terms(
    requirement: RequirementInput,
    discovered_files: list[DiscoveredFile],
    resolved_requirement: dict[str, object] | None,
) -> list[str]:
    terms: list[str] = []
    stems = _name_tokens(requirement.identifier) + _name_tokens(requirement.text) + _name_tokens(requirement.source_snippet)
    if resolved_requirement:
        stems.extend(_name_tokens(str(resolved_requirement.get("name", ""))))
        stems.extend(_name_tokens(" ".join(resolved_requirement.get("bold_terms", []) or [])))
        stems.extend(_name_tokens(str(resolved_requirement.get("file_path", ""))))
    for file in discovered_files:
        if file.kind not in {"source", "test", "harness"}:
            continue
        terms.extend(_path_terms(file.path))
    terms.extend(stems)
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        cleaned = term.strip().lower()
        if len(cleaned) < 3 or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result[:24]


def _same_function_match(hit: RAGHit, requirement: RequirementInput, resolved_requirement: dict[str, object] | None) -> bool:
    function_terms = _name_tokens(requirement.identifier) + _name_tokens(requirement.text) + _name_tokens(requirement.source_snippet)
    if resolved_requirement:
        function_terms.extend(_name_tokens(str(resolved_requirement.get("name", ""))))
    haystack = f"{hit.path} {hit.excerpt} {hit.reason}".lower()
    return any(term in haystack for term in function_terms if len(term) > 3)


def _same_module_match(hit: RAGHit, same_module_terms: list[str]) -> bool:
    haystack = f"{hit.path} {hit.excerpt} {hit.reason}".lower()
    return any(term in haystack for term in same_module_terms if len(term) > 3)


def _confidence_score(
    *,
    has_requirement_evidence: bool,
    has_source_evidence: bool,
    has_dictionary_evidence: bool,
    has_example_evidence: bool,
    has_same_example: bool,
    hits: list[RAGHit],
) -> float:
    score = 0.0
    score += 0.2 if has_requirement_evidence else 0.0
    score += 0.2 if has_source_evidence else 0.0
    score += 0.2 if has_dictionary_evidence else 0.0
    score += 0.2 if has_example_evidence else 0.0
    score += 0.1 if has_same_example else 0.0
    score += min(0.1, sum(hit.score for hit in hits[:3]) / 10.0)
    return min(score, 1.0)


def _recommend_mode(hits: list[RAGHit], same_module_hits: list[RAGHit], requirement: RequirementInput) -> str:
    lower_req = f"{requirement.identifier} {requirement.text} {requirement.source_snippet}".lower()
    same_module_paths = " ".join(hit.path.lower() for hit in same_module_hits)
    if any(token in same_module_paths for token in ("manual-procedures", ".rvstest")):
        return "Manual"
    if any(hit.kind == "harness" for hit in same_module_hits) or any(token in lower_req for token in ("rvstest", "harness", "vector")):
        return "Hybrid"
    if any(hit.kind == "test" for hit in hits):
        return "Direct"
    return "Direct"


def _evidence_summary(hits: list[RAGHit], recommended_mode: str) -> str:
    if not hits:
        return "No repository evidence matched the query."
    top = hits[0]
    return f"Top evidence: {top.path} ({top.kind}, {top.source}). Recommended mode: {recommended_mode}."


def _name_tokens(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]*", text)
    expanded: list[str] = []
    for token in tokens:
        expanded.extend(_split_camel_and_snake(token))
    return [token.lower() for token in expanded if token]


def _split_camel_and_snake(token: str) -> list[str]:
    parts = re.split(r"[_\-]+", token)
    expanded: list[str] = []
    for part in parts:
        if not part:
            continue
        camel = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", part).split()
        expanded.extend(camel or [part])
    return expanded


def _path_terms(path: str) -> list[str]:
    parts = Path(path).parts
    useful = [part for part in parts if part not in {".", ".."}]
    tokens: list[str] = []
    for part in useful[-5:]:
        tokens.extend(_name_tokens(part))
    return tokens


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(errors="ignore")
    except Exception:
        return ""
