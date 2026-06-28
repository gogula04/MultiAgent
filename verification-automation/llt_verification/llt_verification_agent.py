#!/usr/bin/env python3
"""
LLT Verification Agent entrypoint.

This file keeps the user-facing RAG index, query, interactive, and verify
commands in one place while the multi-agent workflow lives in agent_runtime/.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

from agent_runtime.coordinator import run_verification_agent
from agent_runtime.enterprise import EnterpriseControlPlane
from agent_runtime.learning import LearningStore
from agent_runtime.policy import VerificationPolicy
from agent_runtime.poolside import poolside_from_env
from scripts.workspace_utils import detect_workspace_root


EMBEDDING_MODEL = "BAAI/bge-m3"
INDEX_PATH = Path(".faiss_index")
EVIDENCE_EXTENSIONS = {".py", ".h", ".hpp", ".md", ".yaml", ".yml", ".txt", ".csv", ".json", ".rvstest", ".rbtca"}
IGNORED_PARTS = {".git", ".codex", ".faiss_index", "__pycache__", ".venv", "venv", "node_modules", "dist", "build"}
LINE_CHUNK_SIZE = 40
LINE_CHUNK_OVERLAP = 8
SEMANTIC_TOP_K = 6
KEYWORD_TOP_K = 8


@dataclass(frozen=True)
class EvidenceHit:
    source: str
    display_source: str
    line_start: int
    line_end: int
    method: str
    score: float
    content: str
    matched_terms: Tuple[str, ...] = ()

    @property
    def citation(self) -> str:
        return f"{self.display_source}:{self.line_start}-{self.line_end}"


def _is_ignored_path(path: Path) -> bool:
    return any(part in IGNORED_PARTS or part.startswith(".") for part in path.parts)


def _is_allowed_evidence_file(workspace_root: Path, file_path: Path) -> bool:
    if _is_ignored_path(file_path):
        return False
    try:
        relative = file_path.relative_to(workspace_root)
    except Exception:
        return False
    parts = relative.parts
    suffix = file_path.suffix.lower()
    if suffix not in EVIDENCE_EXTENSIONS:
        return False
    if not parts:
        return False
    root = parts[0]
    if root in {"requirements", "references", "agents", "schemas"}:
        return suffix in {".md", ".txt", ".csv", ".yaml", ".yml", ".json"}
    if root == "evals":
        return suffix in {".md", ".txt", ".csv", ".yaml", ".yml", ".json"}
    if root == "verification":
        if len(parts) > 1 and parts[1] in {"test-procedures", "test-cases"}:
            return suffix in {".md", ".txt", ".csv", ".yaml", ".yml", ".json", ".rvstest", ".rbtca", ".py"}
    if root == "records" and len(parts) > 1 and parts[1] == "rbtca":
        return suffix in {".yaml", ".yml", ".json", ".md", ".txt", ".csv", ".rbtca"}
    if root in {"software", "source", "src"}:
        return suffix in {".h", ".hpp"}
    return False


def _iter_line_chunks(lines: Sequence[str], chunk_size: int = LINE_CHUNK_SIZE, overlap: int = LINE_CHUNK_OVERLAP) -> Iterable[Tuple[int, int, str]]:
    if not lines:
        yield 1, 1, ""
        return
    start = 0
    total = len(lines)
    while start < total:
        end = min(start + chunk_size, total)
        chunk = "\n".join(lines[start:end])
        yield start + 1, end, chunk
        if end >= total:
            break
        start = max(end - overlap, start + 1)


def _load_text_file(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8", errors="replace")


def _relative_display_path(workspace_root: Path, file_path: Path) -> str:
    try:
        return str(file_path.relative_to(workspace_root))
    except Exception:
        return str(file_path)


def _document_from_chunk(workspace_root: Path, file_path: Path, line_start: int, line_end: int, chunk_index: int, text: str) -> Document:
    return Document(
        page_content=text,
        metadata={
            "source": str(file_path),
            "display_source": _relative_display_path(workspace_root, file_path),
            "line_start": line_start,
            "line_end": line_end,
            "chunk_index": chunk_index,
            "file_type": file_path.suffix.lower(),
        },
    )


def _line_chunk_documents(workspace_root: Path, file_path: Path) -> List[Document]:
    try:
        text = _load_text_file(file_path)
    except Exception as exc:
        print(f"Warning: Could not load {file_path}: {exc}")
        return []
    lines = text.splitlines()
    documents: List[Document] = []
    for chunk_index, (line_start, line_end, chunk_text) in enumerate(_iter_line_chunks(lines), start=1):
        documents.append(_document_from_chunk(workspace_root, file_path, line_start, line_end, chunk_index, chunk_text))
    return documents


def get_embeddings() -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)


def load_documents(workspace_root: Path) -> List[Document]:
    documents: List[Document] = []
    for file_path in workspace_root.rglob("*"):
        if not file_path.is_file():
            continue
        if not _is_allowed_evidence_file(workspace_root, file_path):
            continue
        documents.extend(_line_chunk_documents(workspace_root, file_path))
    return documents


def create_index(workspace_root: Path) -> FAISS:
    print("Loading documents...")
    documents = load_documents(workspace_root)
    print(f"Loaded {len(documents)} documents")

    print("Creating embeddings and index...")
    vectorstore = FAISS.from_documents(documents, get_embeddings())

    INDEX_PATH.mkdir(exist_ok=True)
    vectorstore.save_local(str(INDEX_PATH))
    print(f"Index saved to {INDEX_PATH}")
    return vectorstore


def load_index() -> Optional[FAISS]:
    if not INDEX_PATH.exists():
        return None
    return FAISS.load_local(str(INDEX_PATH), get_embeddings(), allow_dangerous_deserialization=True)


def _query_tokens(query: str) -> List[str]:
    raw_tokens = re.findall(r"::|->|<=|>=|==|!=|&&|\|\||[A-Za-z0-9_./:-]+", query)
    stop_words = {"the", "and", "or", "for", "with", "from", "that", "this", "shall", "must", "into", "then", "when", "while"}
    tokens = []
    for token in raw_tokens:
        normalized = token.strip()
        if not normalized:
            continue
        if normalized.lower() in stop_words and len(normalized) <= 4:
            continue
        if normalized not in tokens:
            tokens.append(normalized)
    return tokens


def _semantic_hits(vectorstore: FAISS, query: str, limit: int = SEMANTIC_TOP_K) -> List[Tuple[Document, float]]:
    try:
        return vectorstore.similarity_search_with_score(query, k=limit)
    except Exception:
        docs = vectorstore.similarity_search(query, k=limit)
        return [(doc, 0.0) for doc in docs]


def _all_index_documents(vectorstore: FAISS) -> List[Document]:
    try:
        return list(vectorstore.docstore._dict.values())
    except Exception:
        return []


def _keyword_score(doc: Document, tokens: Sequence[str]) -> Tuple[float, Tuple[str, ...]]:
    haystack = "\n".join(
        [
            str(doc.page_content),
            str(doc.metadata.get("source", "")),
            str(doc.metadata.get("display_source", "")),
        ]
    )
    haystack_lower = haystack.lower()
    source_lower = str(doc.metadata.get("source", "")).lower()
    matched: List[str] = []
    score = 0.0
    for token in tokens:
        token_lower = token.lower()
        if not token_lower:
            continue
        if token_lower in haystack_lower:
            matched.append(token)
            base = 3.0 if token_lower in source_lower else 1.5
            if any(ch in token for ch in "_.:/-") or token in {"::", "->", "&&", "||"}:
                base += 1.5
            if token.isupper():
                base += 0.5
            score += base
    return score, tuple(matched)


def _merge_hit(existing: EvidenceHit, new_hit: EvidenceHit) -> EvidenceHit:
    methods = tuple(dict.fromkeys((existing.method, new_hit.method)))
    matched_terms = tuple(dict.fromkeys(existing.matched_terms + new_hit.matched_terms))
    return EvidenceHit(
        source=existing.source,
        display_source=existing.display_source,
        line_start=existing.line_start,
        line_end=existing.line_end,
        method="+".join(methods),
        score=max(existing.score, new_hit.score),
        content=existing.content if len(existing.content) >= len(new_hit.content) else new_hit.content,
        matched_terms=matched_terms,
    )


def retrieve_evidence(vectorstore: FAISS, query: str, semantic_top_k: int = SEMANTIC_TOP_K, keyword_top_k: int = KEYWORD_TOP_K) -> List[EvidenceHit]:
    tokens = _query_tokens(query)
    merged: Dict[Tuple[str, int, int], EvidenceHit] = {}

    for doc, distance in _semantic_hits(vectorstore, query, semantic_top_k):
        metadata = doc.metadata or {}
        source = str(metadata.get("source", "unknown"))
        display_source = str(metadata.get("display_source", source))
        line_start = int(metadata.get("line_start") or 1)
        line_end = int(metadata.get("line_end") or line_start)
        score = 1.0 / (1.0 + float(distance or 0.0))
        hit = EvidenceHit(
            source=source,
            display_source=display_source,
            line_start=line_start,
            line_end=line_end,
            method="semantic",
            score=score,
            content=str(doc.page_content).strip(),
        )
        key = (source, line_start, line_end)
        merged[key] = _merge_hit(merged[key], hit) if key in merged else hit

    keyword_scored: List[Tuple[float, Document, Tuple[str, ...]]] = []
    for doc in _all_index_documents(vectorstore):
        score, matched_terms = _keyword_score(doc, tokens)
        if score > 0:
            keyword_scored.append((score, doc, matched_terms))
    keyword_scored.sort(key=lambda item: item[0], reverse=True)

    for score, doc, matched_terms in keyword_scored[: max(keyword_top_k * 3, keyword_top_k)]:
        metadata = doc.metadata or {}
        source = str(metadata.get("source", "unknown"))
        display_source = str(metadata.get("display_source", source))
        line_start = int(metadata.get("line_start") or 1)
        line_end = int(metadata.get("line_end") or line_start)
        hit = EvidenceHit(
            source=source,
            display_source=display_source,
            line_start=line_start,
            line_end=line_end,
            method="keyword",
            score=float(score),
            content=str(doc.page_content).strip(),
            matched_terms=matched_terms,
        )
        key = (source, line_start, line_end)
        merged[key] = _merge_hit(merged[key], hit) if key in merged else hit

    results = sorted(
        merged.values(),
        key=lambda hit: (hit.score, -hit.line_start, -hit.line_end),
        reverse=True,
    )
    return results[: max(semantic_top_k, keyword_top_k)]


def render_evidence_context(hits: Sequence[EvidenceHit]) -> str:
    sections: List[str] = []
    for index, hit in enumerate(hits, start=1):
        header = f"[{index}] {hit.method} | {hit.citation} | score={hit.score:.3f}"
        if hit.matched_terms:
            header += f" | matches={', '.join(hit.matched_terms)}"
        sections.append(f"{header}\n{hit.content}")
    return "\n\n".join(sections)


def retrieve_code_context(vectorstore: FAISS, query: str) -> Tuple[str, List[EvidenceHit]]:
    hits = retrieve_evidence(vectorstore, query)
    return render_evidence_context(hits), hits


def query_poolside_with_context(query: str, context: str, hits: Sequence[EvidenceHit]) -> str:
    client = poolside_from_env()
    response = client.complete(
        "repo_query",
        {
            "question": query,
            "context": context,
            "evidence": [asdict(hit) for hit in hits],
            "instructions": "Answer using only the repo evidence. Every factual claim should cite a file path and line range from the evidence. If the evidence is insufficient, say so.",
        },
    )
    if isinstance(response.get("parsed_content"), dict):
        parsed = response["parsed_content"]
        if isinstance(parsed, dict) and parsed.get("summary"):
            return json.dumps(parsed, indent=2, sort_keys=False)
    return response.get("content") or response.get("raw") or json.dumps(response, indent=2, sort_keys=False)


def interactive_mode(vectorstore: FAISS) -> None:
    print("\n" + "=" * 60)
    print("LLT Verification Agent - Interactive Mode")
    print("=" * 60)
    print("Ask questions about the repo, verification flow, or requirements.")
    print("Type 'quit' to exit.\n")

    while True:
        try:
            query = input("\n> ").strip()
            if query.lower() in {"quit", "exit", "q"}:
                break
            if not query:
                continue
            context, hits = retrieve_code_context(vectorstore, query)
            print(f"\nAnalyzing... (found {len(hits)} relevant evidence chunks)")
            print("\nEvidence:")
            for index, hit in enumerate(hits, start=1):
                print(f"  [{index}] {hit.citation} ({hit.method}, score={hit.score:.3f})")
            print("\n" + query_poolside_with_context(query, context, hits))
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as exc:
            print(f"Error: {exc}")


def query_mode(vectorstore: FAISS, query: str) -> None:
    context, hits = retrieve_code_context(vectorstore, query)
    print(f"\nFound {len(hits)} relevant evidence chunks")
    print("\n" + "=" * 60)
    print("RESULT")
    print("=" * 60)
    print("Evidence:")
    for index, hit in enumerate(hits, start=1):
        print(f"  [{index}] {hit.citation} ({hit.method}, score={hit.score:.3f})")
    print("\n" + query_poolside_with_context(query, context, hits))


def verify_mode(
    workspace_root: Path,
    requirement: str,
    dry_run: bool = False,
    continue_on_failure: bool = False,
    allow_implementation_reads: bool = False,
    tenant_id: Optional[str] = None,
    user_role: Optional[str] = None,
) -> dict:
    return run_verification_agent(
        requirement,
        workspace_root=str(workspace_root),
        dry_run=dry_run,
        continue_on_failure=continue_on_failure,
        allow_implementation_reads=allow_implementation_reads,
        tenant_id=tenant_id,
        user_role=user_role,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="LLT Verification Agent")
    parser.add_argument("prompt", nargs="?", help='Prompt-style input such as "verify requirement FAF-LLR-401"')
    parser.add_argument("--index", action="store_true", help="Build the vector index")
    parser.add_argument("--query", type=str, help="Run a single query")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive chat mode")
    parser.add_argument("--verify", type=str, help='Run the full LLT verification flow')
    parser.add_argument("--workspace", type=str, default=".", help="Workspace root directory")
    parser.add_argument("--dry-run", action="store_true", help="Preview verification without writing files")
    parser.add_argument("--continue-on-failure", action="store_true", help="Keep debugging and rerunning after a failed test")
    parser.add_argument("--allow-implementation-reads", action="store_true", help="Exception-only approval to read implementation/source files")
    parser.add_argument("--replay-learning-case", type=str, help="Replay one approved learned case by case ID")
    parser.add_argument("--replay-learning-evals", action="store_true", help="Replay the approved learned eval set")
    parser.add_argument("--replay-learning-limit", type=int, help="Limit how many learned evals are replayed")
    parser.add_argument("--replay-learning-execute", action="store_true", help="Execute replay runs instead of dry-run only")
    parser.add_argument("--tenant-id", type=str, default=os.getenv("LLT_TENANT_ID", "default"), help="Enterprise tenant scope")
    parser.add_argument("--user-role", type=str, default=os.getenv("LLT_USER_ROLE", "engineer"), help="Enterprise user role")
    parser.add_argument("--submit-job", type=str, help="Submit a verification job to the enterprise queue")
    parser.add_argument("--approve-job", type=str, help="Approve a queued enterprise job")
    parser.add_argument("--run-queue", action="store_true", help="Run approved enterprise jobs asynchronously")
    parser.add_argument("--enterprise-dashboard", action="store_true", help="Render the enterprise dashboard and metrics")
    parser.add_argument("--enterprise-regression-evals", action="store_true", help="Run enterprise regression evals for activation, retrieval, selection, and proof quality")
    parser.add_argument("--enterprise-list-jobs", action="store_true", help="List enterprise jobs for the active tenant")

    args = parser.parse_args()
    workspace_root = detect_workspace_root(args.workspace)

    if not os.environ.get("POOLSIDE_API_KEY"):
        print("Error: POOLSIDE_API_KEY environment variable not set")
        sys.exit(1)

    if args.index:
        create_index(workspace_root)
        print("Index created successfully")
        return

    control_plane = EnterpriseControlPlane(workspace_root, tenant_id=args.tenant_id, user_role=args.user_role)

    if args.submit_job:
        submitted = control_plane.submit_job(
            args.submit_job,
            dry_run=args.dry_run,
            allow_implementation_reads=args.allow_implementation_reads,
            auto_learning_approved=os.getenv("LLT_AUTO_LEARNING_APPROVED", "").strip().lower() in {"1", "true", "yes", "on"},
        )
        print(json.dumps(submitted, indent=2, default=str))
        return

    if args.approve_job:
        approved = control_plane.approve_job(args.approve_job, approver=args.user_role)
        print(json.dumps(approved, indent=2, default=str))
        return

    if args.run_queue:
        result = control_plane.run_pending_jobs()
        print(json.dumps(result, indent=2, default=str))
        return

    if args.enterprise_dashboard:
        dashboard = control_plane.render_dashboard()
        print(json.dumps(dashboard, indent=2, default=str))
        return

    if args.enterprise_regression_evals:
        report = control_plane.build_regression_evals()
        print(json.dumps(report, indent=2, default=str))
        return

    if args.enterprise_list_jobs:
        print(json.dumps(control_plane.list_jobs(), indent=2, default=str))
        return

    if args.replay_learning_case or args.replay_learning_evals:
        replay_policy = VerificationPolicy.from_env(
            tenant_id=args.tenant_id,
            user_role=args.user_role,
        )
        learning_store = LearningStore(type("RuntimeShim", (), {"workspace_root": workspace_root, "policy": replay_policy, "generated_files": []})())
        if args.replay_learning_case:
            replay = learning_store.replay_learning_case(
                args.replay_learning_case,
                dry_run=not args.replay_learning_execute,
                allow_implementation_reads=args.allow_implementation_reads,
            )
        else:
            replay = learning_store.replay_learning_cases(
                limit=args.replay_learning_limit,
                dry_run=not args.replay_learning_execute,
                allow_implementation_reads=args.allow_implementation_reads,
            )
        print("\n" + "=" * 60)
        print("LEARNING REPLAY REPORT")
        print("=" * 60)
        print(json.dumps(replay, indent=2, default=str))
        return

    vectorstore = load_index()
    if not vectorstore:
        print("No index found. Run with --index to create one first.")
        sys.exit(1)

    if args.interactive:
        interactive_mode(vectorstore)
    elif args.verify:
        result = verify_mode(
            workspace_root,
            args.verify,
            dry_run=args.dry_run,
            continue_on_failure=args.continue_on_failure,
            allow_implementation_reads=args.allow_implementation_reads,
            tenant_id=args.tenant_id,
            user_role=args.user_role,
        )
        print("\n" + "=" * 60)
        print("LLT VERIFICATION REPORT")
        print("=" * 60)
        print(json.dumps(result, indent=2, default=str))
    elif args.prompt:
        prompt = args.prompt.strip()
        if re.search(r"FAF-LLR-\d+", prompt) or prompt.lower().startswith("verify requirement"):
            result = verify_mode(
                workspace_root,
                prompt,
                dry_run=args.dry_run,
                continue_on_failure=args.continue_on_failure,
                allow_implementation_reads=args.allow_implementation_reads,
                tenant_id=args.tenant_id,
                user_role=args.user_role,
            )
            print("\n" + "=" * 60)
            print("LLT VERIFICATION REPORT")
            print("=" * 60)
            print(json.dumps(result, indent=2, default=str))
        else:
            query_mode(vectorstore, prompt)
    elif args.query:
        query_mode(vectorstore, args.query)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
