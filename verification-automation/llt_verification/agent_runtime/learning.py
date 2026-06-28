"""Controlled offline learning for approved verification runs."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

from .core import normalize_term


EMBEDDING_MODEL = "BAAI/bge-m3"
LEARNING_CASE_DIR_NAME = "learned_cases"
LEARNING_TEMPLATE_DIR_NAME = "learned_templates"
LEARNING_EVAL_FILE = "learned_evals.json"
LEARNING_TEMPLATE_FILE = "learning-case-template.json"
LEARNING_DIRECT_TEMPLATE_FILE = "direct-template.json"
LEARNING_HYBRID_TEMPLATE_FILE = "hybrid-template.json"
LINE_CHUNK_SIZE = 40
LINE_CHUNK_OVERLAP = 8
REUSE_MIN_SCORE = 3.0
REUSE_MEDIUM_SCORE = 4.5
REUSE_HIGH_SCORE = 6.0


def _iter_line_chunks(lines: Sequence[str], chunk_size: int = LINE_CHUNK_SIZE, overlap: int = LINE_CHUNK_OVERLAP) -> Iterable[Tuple[int, int, str]]:
    if not lines:
        yield 1, 1, ""
        return
    start = 0
    total = len(lines)
    while start < total:
        end = min(start + chunk_size, total)
        yield start + 1, end, "\n".join(lines[start:end])
        if end >= total:
            break
        start = max(end - overlap, start + 1)


def _document_from_text(workspace_root: Path, file_path: Path, text: str) -> List[Document]:
    documents: List[Document] = []
    lines = text.splitlines()
    for chunk_index, (line_start, line_end, chunk_text) in enumerate(_iter_line_chunks(lines), start=1):
        documents.append(
            Document(
                page_content=chunk_text,
                metadata={
                    "source": str(file_path),
                    "display_source": str(file_path.relative_to(workspace_root)) if file_path.is_relative_to(workspace_root) else str(file_path),
                    "line_start": line_start,
                    "line_end": line_end,
                    "chunk_index": chunk_index,
                    "file_type": file_path.suffix.lower(),
                },
            )
        )
    return documents


def get_embeddings() -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)


class LearningStore:
    def __init__(self, runtime: "VerificationCoordinator"):
        self.runtime = runtime
        self.workspace_root = runtime.workspace_root
        self.tenant_scope = getattr(runtime.policy, "tenant_scope_path", lambda: "shared")()
        self.learning_dir = self.workspace_root / "evals" / LEARNING_CASE_DIR_NAME / self.tenant_scope
        self.template_dir = self.workspace_root / "evals" / LEARNING_TEMPLATE_DIR_NAME / self.tenant_scope
        self.template_path = self.workspace_root / "references" / LEARNING_TEMPLATE_FILE
        self.evals_file = self.learning_dir / LEARNING_EVAL_FILE
        self.index_manifest = self.learning_dir / "index.json"

    def _learning_enabled(self) -> bool:
        return bool(getattr(self.runtime.policy, "auto_learning_allowed", lambda: False)())

    def _write_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=False, default=str))
        self.runtime.generated_files.append(str(path))

    def _case_tokens(self, values: Any) -> List[str]:
        tokens: List[str] = []

        def add(value: Any) -> None:
            if value is None:
                return
            text = str(value).strip().lower()
            if not text:
                return
            for token in re.findall(r"[a-z0-9_./:-]+", text):
                token = token.strip()
                if token and token not in tokens:
                    tokens.append(token)

        if isinstance(values, dict):
            for key, value in values.items():
                add(key)
                add(value)
            return tokens
        if isinstance(values, (list, tuple, set)):
            for item in values:
                add(item)
            return tokens
        add(values)
        return tokens

    def _load_json_file(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            loaded = json.loads(path.read_text())
        except Exception:
            return None
        return loaded if isinstance(loaded, dict) else None

    def _method_confidence(self, score: float, overlap_count: int) -> str:
        if score >= REUSE_HIGH_SCORE and overlap_count >= 4:
            return "high"
        if score >= REUSE_MEDIUM_SCORE and overlap_count >= 3:
            return "medium"
        return "low"

    def _is_direct_method(self, case: Dict[str, Any]) -> bool:
        return str(case.get("selected_method") or "").lower() == "direct"

    def _is_hybrid_method(self, case: Dict[str, Any]) -> bool:
        return str(case.get("selected_method") or "").lower() == "hybrid"

    def _method_template_path(self, selected_method: str) -> Path:
        method = "hybrid" if selected_method == "hybrid" else "direct"
        return self.template_dir / f"{method}-template.json"

    def _method_template_markdown_path(self, selected_method: str) -> Path:
        method = "hybrid" if selected_method == "hybrid" else "direct"
        return self.template_dir / f"{method}-template.md"

    def _load_learning_cases(self) -> List[Dict[str, Any]]:
        cases: List[Dict[str, Any]] = []
        if self.evals_file.exists():
            loaded = self._load_json_file(self.evals_file)
            if loaded and isinstance(loaded.get("evals"), list):
                cases.extend(item for item in loaded["evals"] if isinstance(item, dict))
        if self.learning_dir.exists():
            for case_file in sorted(self.learning_dir.glob("*.json")):
                if case_file == self.evals_file or case_file == self.index_manifest:
                    continue
                loaded = self._load_json_file(case_file)
                if loaded:
                    loaded.setdefault("case_file", str(case_file))
                    loaded.setdefault("tenant_id", self.tenant_scope)
                    cases.append(loaded)
        return cases

    def list_learning_cases(self) -> List[Dict[str, Any]]:
        return self._load_learning_cases()

    def get_learning_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        target = normalize_term(case_id)
        for case in self._load_learning_cases():
            candidate_id = normalize_term(str(case.get("case_id") or case.get("requirement_id") or ""))
            if candidate_id == target:
                return case
        return None

    def _score_case(self, request_tokens: List[str], case: Dict[str, Any]) -> Tuple[float, List[str]]:
        case_tokens = self._case_tokens(
            [
                case.get("requirement_text"),
                case.get("prompt"),
                case.get("expected_output"),
                case.get("selected_method"),
                case.get("branch_note"),
                case.get("method_reason"),
                case.get("requirement_package", {}).get("inputs", []),
                case.get("requirement_package", {}).get("outputs", []),
                case.get("normalized_terms_package", {}).get("normalized_terms", []),
                case.get("normalized_terms_package", {}).get("aliases", {}),
                case.get("reuse_hints", []),
                case.get("review_status"),
                case.get("execution_status"),
            ]
        )
        overlaps = sorted(set(request_tokens).intersection(case_tokens))
        score = float(len(overlaps))
        if case.get("selected_method") == "hybrid":
            score += 0.5
        if case.get("review_status") == "approved":
            score += 0.5
        if case.get("execution_status") == "passed":
            score += 0.5
        return score, overlaps

    def _append_manifest(self, entry: Dict[str, Any]) -> None:
        manifest: List[Dict[str, Any]] = []
        if self.index_manifest.exists():
            try:
                loaded = json.loads(self.index_manifest.read_text())
                if isinstance(loaded, list):
                    manifest = loaded
            except Exception:
                manifest = []
        manifest.append(entry)
        self._write_json(self.index_manifest, manifest)

    def _ensure_template(self) -> bool:
        if self.template_path.exists():
            return False
        template = {
            "case_id": "<case_id>",
            "requirement_id": "<requirement_id>",
            "requirement_text": "<requirement_text>",
            "selected_method": "<direct|hybrid>",
            "branch_note": "<branch_note>",
            "status": "<passed>",
            "approved_only": True,
            "sources": {
                "requirement_package": {},
                "evidence_package": {},
                "normalized_terms_package": {},
                "analysis_package": {},
                "strategy_decision": {},
                "artifact_patch": {},
                "traceability_result": {},
                "execution_result": {},
                "debug_result": {},
                "review_result": {},
            },
            "reuse_hints": [],
            "generated_at": "<timestamp>",
        }
        self.template_path.parent.mkdir(parents=True, exist_ok=True)
        self.template_path.write_text(json.dumps(template, indent=2, sort_keys=False))
        self.runtime.generated_files.append(str(self.template_path))
        return True

    def _case_summary(self, report: Dict[str, Any], case_id: str) -> Dict[str, Any]:
        requirement_id = str(report.get("requirement_id") or "generated")
        decision = report.get("method_decision", {}) or {}
        review = report.get("review", {}) or {}
        execution = report.get("execution_result", {}) or {}
        requirement_package = report.get("requirement", {}) or {}
        normalization_package = report.get("normalized_terms", {}) or {}
        reuse_candidates = report.get("reuse_candidates", []) or []
        top_candidate = reuse_candidates[0] if reuse_candidates and isinstance(reuse_candidates[0], dict) else {}
        return {
            "case_id": case_id,
            "requirement_id": requirement_id,
            "selected_method": report.get("method_decision", {}).get("selected_method"),
            "requirement_text": requirement_package.get("requirement_text"),
            "branch_note": report.get("branch_note"),
            "prompt": f"verify requirement {requirement_id}",
            "expected_output": f"Approved {decision.get('selected_method')} verification case with proof and review status {review.get('status', 'unknown')}",
            "execution_status": execution.get("status"),
            "review_status": review.get("status"),
            "normalized_terms": normalization_package.get("normalized_terms", []),
            "reuse_hints": normalization_package.get("aliases", {}),
            "review_summary": review.get("summary"),
            "method_reason": decision.get("reason"),
            "reuse_score": top_candidate.get("score"),
            "reuse_confidence": top_candidate.get("confidence"),
            "reuse_matched_terms": top_candidate.get("matched_terms", []),
        }

    def _build_case(self, report: Dict[str, Any]) -> Dict[str, Any]:
        requirement = report.get("requirement", {}) or {}
        evidence = report.get("evidence", {}) or {}
        normalization = report.get("normalized_terms", {}) or {}
        analysis = report.get("analysis", {}) or {}
        decision = report.get("method_decision", {}) or {}
        artifacts = report.get("artifacts", {}) or {}
        traceability = report.get("traceability", {}) or {}
        execution = report.get("execution_result", {}) or {}
        debug_result = report.get("debug_result", {}) or {}
        review = report.get("review", {}) or {}
        reuse_candidates = report.get("reuse_candidates", []) or []
        top_candidate = reuse_candidates[0] if reuse_candidates and isinstance(reuse_candidates[0], dict) else {}
        case_id = f"{report.get('requirement_id', 'generated')}-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
        aliases = normalization.get("aliases", {}) if isinstance(normalization, dict) else {}
        reuse_hints: List[Dict[str, Any]] = []
        for term, meta in aliases.items():
            if not isinstance(meta, dict):
                continue
            reuse_hints.append(
                {
                    "term": term,
                    "normalized": meta.get("normalized"),
                    "dd_name": meta.get("dd_name"),
                    "variants": meta.get("variants", []),
                    "method": decision.get("selected_method"),
                }
            )
        return {
            "case_id": case_id,
            "approved_only": True,
            "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "tenant_id": self.tenant_scope,
            "requirement_id": report.get("requirement_id"),
            "requirement_text": requirement.get("requirement_text"),
            "component_name": requirement.get("component_name"),
            "branch_note": report.get("branch_note"),
            "selected_method": decision.get("selected_method"),
            "method_reason": decision.get("reason"),
            "method_proof": report.get("method_proof", []),
            "status": report.get("status"),
            "review_status": review.get("status"),
            "execution_status": execution.get("status"),
            "traceability_passed": traceability.get("passed"),
            "reuse_score": top_candidate.get("score"),
            "reuse_confidence": top_candidate.get("confidence"),
            "reuse_matched_terms": top_candidate.get("matched_terms", []),
            "policy": self.runtime.policy.manifest(),
            "run_manifest": report.get("run_manifest", {}),
            "requirement_package": requirement,
            "evidence_package": evidence,
            "normalized_terms_package": normalization,
            "analysis_package": analysis,
            "strategy_decision": decision,
            "artifact_patch": artifacts,
            "traceability_result": traceability,
            "execution_result": execution,
            "debug_result": debug_result,
            "review_result": review,
            "alias_trace": report.get("alias_trace", {}),
            "extraction_aliases": report.get("extraction_aliases", {}),
            "evidence_citations": decision.get("evidence", {}).get("citations", {}),
            "reuse_hints": reuse_hints,
            "reuse_candidates": reuse_candidates,
            "artifacts": {
                "files_created": artifacts.get("files_created", []),
                "files_updated": artifacts.get("files_updated", []),
                "rbtca_file": artifacts.get("rbtca_file"),
                "test_file": artifacts.get("test_file"),
                "rvstest_file": artifacts.get("rvstest_file"),
            },
        }

    def _render_case_markdown(self, case: Dict[str, Any]) -> str:
        lines = [
            "# Learned Verification Case",
            "",
            f"- Case ID: {case.get('case_id')}",
            f"- Requirement ID: {case.get('requirement_id')}",
            f"- Selected Method: {case.get('selected_method')}",
            f"- Review Status: {case.get('review_status')}",
            f"- Execution Status: {case.get('execution_status')}",
            f"- Branch Note: {case.get('branch_note')}",
            "",
            "## Reuse Hints",
        ]
        reuse_hints = case.get("reuse_hints", []) or []
        if reuse_hints:
            lines.extend(["| Term | Normalized | DD Name | Variants |", "| --- | --- | --- | --- |"])
            for hint in reuse_hints:
                lines.append(
                    f"| {hint.get('term', '')} | {hint.get('normalized', '')} | {hint.get('dd_name', '')} | {', '.join(str(v) for v in hint.get('variants', []) or [])} |"
                )
        else:
            lines.append("No reuse hints were captured.")
        lines.extend(
            [
                "",
                "## Evidence Snapshot",
                json.dumps(
                    {
                        "evidence_citations": case.get("evidence_citations", {}),
                        "method_reason": case.get("method_reason"),
                        "method_proof": case.get("method_proof", []),
                    },
                    indent=2,
                    sort_keys=False,
                    default=str,
                ),
            ]
        )
        return "\n".join(lines)

    def _build_method_template(self, case: Dict[str, Any]) -> Dict[str, Any]:
        selected_method = "hybrid" if self._is_hybrid_method(case) else "direct"
        required_updates = (
            [
                "verification/test-procedures/procedure-data/data_dictionary.csv",
                "verification/test-procedures/procedure-data/data_dictionary.yaml",
                "verification/test-procedures/procedure-data/uut_dictionary.csv",
                "verification/test-procedures/procedure-data/uut_dictionary.yaml",
                "verification/test-procedures/procedure-data/types_struct.csv if needed",
                "generate RBTCA",
                "generate Python tests",
            ]
            if selected_method == "direct"
            else [
                "verification/test-procedures/procedure-data/data_dictionary.csv",
                "verification/test-procedures/procedure-data/data_dictionary.yaml",
                "generate .rvstest",
                "generate RBTCA",
                "generate Python tests",
            ]
        )
        return {
            "case_id": case.get("case_id"),
            "requirement_id": case.get("requirement_id"),
            "selected_method": selected_method,
            "branch_note": case.get("branch_note"),
            "confidence": case.get("reuse_confidence", "unknown"),
            "score": case.get("reuse_score"),
            "matched_terms": case.get("reuse_matched_terms", []),
            "reuse_hints": case.get("reuse_hints", []),
            "required_updates": required_updates,
            "evidence_citations": case.get("evidence_citations", {}),
            "artifact_paths": case.get("artifacts", {}),
            "offline_only": True,
            "approved_only": True,
            "generated_at": case.get("generated_at"),
        }

    def _render_method_template_markdown(self, template: Dict[str, Any]) -> str:
        lines = [
            "# Learned Method Template",
            "",
            f"- Case ID: {template.get('case_id')}",
            f"- Requirement ID: {template.get('requirement_id')}",
            f"- Selected Method: {template.get('selected_method')}",
            f"- Confidence: {template.get('confidence')}",
            f"- Score: {template.get('score')}",
            "",
            "## Required Updates",
        ]
        for item in template.get("required_updates", []) or []:
            lines.append(f"- {item}")
        lines.extend(
            [
                "",
                "## Matched Terms",
                ", ".join(str(term) for term in template.get("matched_terms", []) or []) or "None",
                "",
                "## Reuse Hints",
                json.dumps(template.get("reuse_hints", []), indent=2, sort_keys=False, default=str),
                "",
                "## Evidence Citations",
                json.dumps(template.get("evidence_citations", {}), indent=2, sort_keys=False, default=str),
            ]
        )
        return "\n".join(lines)

    def _write_method_templates(self, case: Dict[str, Any]) -> Dict[str, Any]:
        template = self._build_method_template(case)
        template_path = self._method_template_path(template["selected_method"])
        template_md_path = self._method_template_markdown_path(template["selected_method"])
        self.template_dir.mkdir(parents=True, exist_ok=True)
        template_path.write_text(json.dumps(template, indent=2, sort_keys=False, default=str))
        template_md_path.write_text(self._render_method_template_markdown(template))
        self.runtime.generated_files.extend([str(template_path), str(template_md_path)])
        return {"template_file": str(template_path), "template_markdown": str(template_md_path)}

    def _write_evals_file(self, cases: List[Dict[str, Any]]) -> Path:
        payload = {
            "skill_name": "llt-verification",
            "generated_from": "approved_verification_runs",
            "learning_enabled": True,
            "tenant_id": self.tenant_scope,
            "evals": cases,
        }
        self._write_json(self.evals_file, payload)
        return self.evals_file

    def _update_vector_index(self, file_paths: Sequence[Path]) -> Dict[str, Any]:
        docs: List[Document] = []
        for file_path in file_paths:
            if not file_path.exists() or not file_path.is_file():
                continue
            try:
                text = file_path.read_text(errors="replace")
            except Exception:
                continue
            docs.extend(_document_from_text(self.workspace_root, file_path, text))
        if not docs:
            return {"status": "skipped", "reason": "no documents to index"}
        index_path = self.workspace_root / ".faiss_index"
        try:
            vectorstore = FAISS.load_local(str(index_path), get_embeddings(), allow_dangerous_deserialization=True)
        except Exception:
            vectorstore = None
        if vectorstore is None:
            vectorstore = FAISS.from_documents(docs, get_embeddings())
        else:
            vectorstore.add_documents(docs)
        vectorstore.save_local(str(index_path))
        return {"status": "updated", "documents_indexed": len(docs), "index_path": str(index_path)}

    def find_similar_cases(self, requirement_package: Dict[str, Any], evidence_package: Dict[str, Any], normalization_package: Dict[str, Any], limit: int = 3) -> List[Dict[str, Any]]:
        request_tokens = self._case_tokens(
            [
                requirement_package.get("requirement_text"),
                requirement_package.get("classification"),
                requirement_package.get("bold_terms", []),
                requirement_package.get("inputs", []),
                requirement_package.get("outputs", []),
                requirement_package.get("types_and_ranges", []),
                requirement_package.get("expressions", {}),
                normalization_package.get("normalized_terms", []),
                normalization_package.get("aliases", {}),
                evidence_package.get("data_dictionary_findings", {}),
                evidence_package.get("uut_dictionary_findings", {}),
            ]
        )
        candidates: List[Tuple[float, Dict[str, Any], List[str]]] = []
        for case in self._load_learning_cases():
            if str(case.get("tenant_id") or self.tenant_scope) != self.tenant_scope:
                continue
            score, overlaps = self._score_case(request_tokens, case)
            if score < REUSE_MIN_SCORE:
                continue
            confidence = self._method_confidence(score, len(overlaps))
            candidate = {
                "case_id": case.get("case_id"),
                "requirement_id": case.get("requirement_id"),
                "selected_method": case.get("selected_method"),
                "review_status": case.get("review_status"),
                "execution_status": case.get("execution_status"),
                "score": score,
                "confidence": confidence,
                "confidence_score": round(min(score / REUSE_HIGH_SCORE, 1.0), 3),
                "reuse_recommended": confidence in {"high", "medium"},
                "matched_terms": overlaps,
                "match_count": len(overlaps),
                "branch_note": case.get("branch_note"),
                "case_file": case.get("case_file"),
                "normalized_terms": case.get("normalized_terms", []),
                "reuse_hints": case.get("reuse_hints", {}),
                "method_reason": case.get("method_reason"),
            }
            candidates.append((score, candidate, overlaps))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [candidate for _, candidate, _ in candidates[:limit]]

    def replay_learning_case(self, case_id: str, dry_run: bool = True, allow_implementation_reads: bool = False) -> Dict[str, Any]:
        case = self.get_learning_case(case_id)
        if not case:
            return {"status": "missing", "case_id": case_id, "reason": "learning case not found"}
        requirement_text = case.get("requirement_text") or case.get("prompt") or case.get("requirement_id") or case_id
        from .coordinator import run_verification_agent

        result = run_verification_agent(
            requirement_text,
            workspace_root=str(self.workspace_root),
            dry_run=dry_run,
            continue_on_failure=False,
            allow_implementation_reads=allow_implementation_reads,
            auto_learning_approved=False,
            tenant_id=self.tenant_scope,
            user_role=getattr(self.runtime.policy, "normalized_user_role", lambda: "engineer")(),
        )
        return {
            "status": "replayed",
            "case_id": case.get("case_id", case_id),
            "requirement_id": case.get("requirement_id"),
            "dry_run": dry_run,
            "learning_case_file": case.get("case_file"),
            "replay_result": result,
        }

    def replay_learning_cases(self, limit: Optional[int] = None, dry_run: bool = True, allow_implementation_reads: bool = False) -> Dict[str, Any]:
        cases = self._load_learning_cases()
        if limit is not None:
            cases = cases[:limit]
        results = [self.replay_learning_case(str(case.get("case_id") or case.get("requirement_id") or idx), dry_run=dry_run, allow_implementation_reads=allow_implementation_reads) for idx, case in enumerate(cases, start=1)]
        return {
            "status": "completed",
            "count": len(results),
            "dry_run": dry_run,
            "results": results,
        }

    def record_approved_case(self, report: Dict[str, Any]) -> Dict[str, Any]:
        if not self._learning_enabled():
            return {"status": "skipped", "reason": "auto-learning gate disabled", "files_created": [], "index_update": {"status": "skipped"}}
        execution_status = str((report.get("execution_result") or {}).get("status") or "")
        if report.get("status") != "passed" or execution_status != "passed" or (report.get("review", {}) or {}).get("status") != "approved":
            return {
                "status": "skipped",
                "reason": "run was not approved with a passed execution result",
                "files_created": [],
                "index_update": {"status": "skipped"},
            }
        template_created = self._ensure_template()
        case = self._build_case(report)
        case["tenant_id"] = self.tenant_scope
        case_path = self.learning_dir / f"{normalize_term(case['case_id'])}.json"
        md_path = case_path.with_suffix(".md")
        self._write_json(case_path, case)
        md_path.write_text(self._render_case_markdown(case))
        self.runtime.generated_files.append(str(md_path))
        summary = self._case_summary(report, case["case_id"])
        self._append_manifest(summary)
        template_result = self._write_method_templates(case)
        cases: List[Dict[str, Any]] = []
        if self.evals_file.exists():
            try:
                loaded = json.loads(self.evals_file.read_text())
                if isinstance(loaded, dict):
                    cases = list(loaded.get("evals", []))
            except Exception:
                cases = []
        cases.append(summary)
        self._write_evals_file(cases)
        index_update = self._update_vector_index([case_path, md_path, self.evals_file, self.index_manifest, self.template_path])
        files_created = [str(case_path), str(md_path), str(self.evals_file), str(self.index_manifest), template_result["template_file"], template_result["template_markdown"]]
        if template_created:
            files_created.append(str(self.template_path))
        return {
            "status": "created",
            "case_id": case["case_id"],
            "case_file": str(case_path),
            "case_markdown": str(md_path),
            "template_file": str(self.template_path),
            "method_template": template_result,
            "evals_file": str(self.evals_file),
            "index_manifest": str(self.index_manifest),
            "index_update": index_update,
            "files_created": files_created,
            "files_updated": [str(self.evals_file), str(self.index_manifest), str(self.workspace_root / ".faiss_index"), template_result["template_file"], template_result["template_markdown"]],
            "approved_only": True,
        }
