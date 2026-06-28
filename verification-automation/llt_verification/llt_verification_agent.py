#!/usr/bin/env python3
"""
LLT Verification Agent entrypoint.

This file keeps the user-facing RAG index, query, interactive, and verify
commands in one place while the peer-agent workflow lives in agent_runtime/.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, List, Optional

from langchain_community.document_loaders import TextLoader
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from agent_runtime.coordinator import run_verification_agent
from agent_runtime.poolside import poolside_from_env
from scripts.workspace_utils import detect_workspace_root


EMBEDDING_MODEL = "BAAI/bge-m3"
INDEX_PATH = Path(".faiss_index")
SOURCE_EXTENSIONS = {".py", ".c", ".h", ".cpp", ".hpp", ".md", ".yaml", ".yml", ".txt", ".csv", ".json"}
IGNORED_PARTS = {".git", ".codex", ".faiss_index", "__pycache__", ".venv", "venv", "node_modules", "dist", "build"}


def _is_ignored_path(path: Path) -> bool:
    return any(part in IGNORED_PARTS or part.startswith(".") for part in path.parts)


def get_embeddings() -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)


def load_documents(workspace_root: Path) -> List[Any]:
    documents: List[Any] = []
    for file_path in workspace_root.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        if _is_ignored_path(file_path):
            continue
        try:
            documents.extend(TextLoader(str(file_path), encoding="utf-8").load())
        except Exception as exc:
            print(f"Warning: Could not load {file_path}: {exc}")
    return documents


def create_index(workspace_root: Path) -> FAISS:
    print("Loading documents...")
    documents = load_documents(workspace_root)
    print(f"Loaded {len(documents)} documents")

    print("Splitting documents...")
    splits = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100).split_documents(documents)
    print(f"Created {len(splits)} chunks")

    print("Creating embeddings and index...")
    vectorstore = FAISS.from_documents(splits, get_embeddings())

    INDEX_PATH.mkdir(exist_ok=True)
    vectorstore.save_local(str(INDEX_PATH))
    print(f"Index saved to {INDEX_PATH}")
    return vectorstore


def load_index() -> Optional[FAISS]:
    if not INDEX_PATH.exists():
        return None
    return FAISS.load_local(str(INDEX_PATH), get_embeddings(), allow_dangerous_deserialization=True)


def retrieve_code_context(vectorstore: FAISS, query: str) -> str:
    retriever = vectorstore.as_retriever(search_kwargs={"k": 5})
    docs = retriever.invoke(query)
    return "\n\n".join(
        f"--- {doc.metadata.get('source', 'unknown')} ---\n{doc.page_content}" for doc in docs
    )


def query_poolside_with_context(query: str, context: str) -> str:
    client = poolside_from_env()
    response = client.complete(
        "repo_query",
        {
            "question": query,
            "context": context,
            "instructions": "Answer using only the repo context. Cite files when useful.",
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
            context = retrieve_code_context(vectorstore, query)
            print(f"\nAnalyzing... (found {len(context.split('---')) - 1} relevant files)")
            print("\n" + query_poolside_with_context(query, context))
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as exc:
            print(f"Error: {exc}")


def query_mode(vectorstore: FAISS, query: str) -> None:
    context = retrieve_code_context(vectorstore, query)
    print(f"\nFound {len(context.split('---')) - 1} relevant files")
    print("\n" + "=" * 60)
    print("RESULT")
    print("=" * 60)
    print(query_poolside_with_context(query, context))


def verify_mode(workspace_root: Path, requirement: str, dry_run: bool = False, continue_on_failure: bool = False) -> dict:
    return run_verification_agent(
        requirement,
        workspace_root=str(workspace_root),
        dry_run=dry_run,
        continue_on_failure=continue_on_failure,
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

    args = parser.parse_args()
    workspace_root = detect_workspace_root(args.workspace)

    if not os.environ.get("POOLSIDE_API_KEY"):
        print("Error: POOLSIDE_API_KEY environment variable not set")
        sys.exit(1)

    if args.index:
        create_index(workspace_root)
        print("Index created successfully")
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
