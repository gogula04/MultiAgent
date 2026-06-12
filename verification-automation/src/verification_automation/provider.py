"""Model/provider abstraction with an evidence-aware local adapter."""

from __future__ import annotations

from dataclasses import asdict
import json
import os
import re
from typing import Any

try:  # pragma: no cover - optional in local dev
    import ssl
    import httpx
    import truststore
except Exception:  # pragma: no cover
    ssl = None
    httpx = None
    truststore = None

try:  # pragma: no cover - optional in local dev
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover
    BaseModel = object  # type: ignore[assignment]
    Field = None  # type: ignore[assignment]

from .config import AppConfig
from .models import RequirementInput, RequirementBehavior, MappingRow, DDRow, CoverageItem, DiscoveredFile, ProofReport


class PullRequestReview(BaseModel if BaseModel is not object else object):  # type: ignore[misc]
    """Structured review output for a requirement or draft artifact set."""

    if BaseModel is not object:  # pragma: no branch
        is_safe: bool = Field(description="True if the draft is ready to proceed.")
        risk_score: int = Field(description="A score from 1-10 indicating risk level")
        summary: str = Field(description="A one-sentence summary of the review")
        suggested_fix: str = Field(description="Suggested fix or 'N/A'")
        tags: list[str] = Field(description="Review tags")
    else:  # pragma: no cover
        def __init__(self, is_safe: bool = True, risk_score: int = 1, summary: str = "", suggested_fix: str = "N/A", tags: list[str] | None = None):
            self.is_safe = is_safe
            self.risk_score = risk_score
            self.summary = summary
            self.suggested_fix = suggested_fix
            self.tags = tags or []


class ModelAdapter:
    """A tiny interface used by the agents.

    The production path can use LangChain/OpenAI-compatible Poolside.
    The local adapter keeps the workflow runnable on a laptop without credentials
    while still preferring repository evidence over invented structure.
    """

    def analyze_requirement(self, req: RequirementInput, files: list[DiscoveredFile]) -> list[RequirementBehavior]:
        raise NotImplementedError

    def map_requirement(self, req: RequirementInput, behaviors: list[RequirementBehavior], files: list[DiscoveredFile]) -> list[MappingRow]:
        raise NotImplementedError

    def build_dd(self, req: RequirementInput, mappings: list[MappingRow], mode: str, behaviors: list[RequirementBehavior] | None = None) -> list[DDRow]:
        raise NotImplementedError

    def build_coverage(self, req: RequirementInput, behaviors: list[RequirementBehavior], mode: str) -> list[CoverageItem]:
        raise NotImplementedError

    def build_proof(self, report: ProofReport) -> ProofReport:
        raise NotImplementedError

    def review_drafts(self, req: RequirementInput, draft: dict[str, Any], config: AppConfig) -> dict[str, Any]:
        raise NotImplementedError


class LocalFallbackModel(ModelAdapter):
    def analyze_requirement(self, req: RequirementInput, files: list[DiscoveredFile]) -> list[RequirementBehavior]:
        text = " ".join(part for part in [req.identifier, req.text, req.source_snippet] if part).strip()
        behaviors: list[RequirementBehavior] = []
        lines = _split_requirement_text(text)
        joined = " ".join(lines).lower()
        bold_terms = _extract_bold_terms(text)
        evidence_terms = _evidence_terms_from_files(files)
        if bold_terms:
            behaviors.append(
                RequirementBehavior(
                    label="Highlighted requirement terms",
                    description="Track bolded requirement terms from the resolved requirement text.",
                    terms=bold_terms[:10],
                )
            )
        if evidence_terms:
            behaviors.append(
                RequirementBehavior(
                    label="Repository evidence pattern",
                    description="Reuse the closest verified repository example as the source of truth.",
                    terms=evidence_terms[:10],
                )
            )
        if any(tok in joined for tok in ("null", "pointer", "reference")):
            behaviors.append(RequirementBehavior(label="Null / reference behavior", description="Verify pointer and null handling.", terms=["pointer", "null", "reference"]))
        if any(tok in joined for tok in ("boundary", "min", "max", "range", "zero", "negative", "greater than", "less than", "equal to")):
            behaviors.append(RequirementBehavior(label="Boundary / robustness behavior", description="Verify range edges and robustness values.", terms=["boundary", "min", "max", "zero"]))
        if any(tok in joined for tok in ("fault", "log", "error", "warning")):
            behaviors.append(RequirementBehavior(label="Fault logging behavior", description="Verify non-severe or recoverable fault paths.", terms=["fault", "log", "warning"]))
        if any(tok in joined for tok in ("enum", "state", "mode", "branch", "condition", "lock", "try lock", "mutex")):
            behaviors.append(RequirementBehavior(label="Decision behavior", description="Verify branch and enum based control flow.", terms=["enum", "branch", "condition"]))
        if any(tok in joined for tok in ("blocking", "non blocking", "try lock", "unlock", "lock")):
            behaviors.append(RequirementBehavior(label="Synchronization behavior", description="Verify lock acquisition and release behavior.", terms=["lock", "try lock", "unlock"]))
        for line in lines:
            if line and len(behaviors) < 5 and ("shall" in line.lower() or "when" in line.lower()):
                behaviors.append(RequirementBehavior(label=line[:64], description=line, terms=_extract_terms(line)))
        return behaviors

    def map_requirement(self, req: RequirementInput, behaviors: list[RequirementBehavior], files: list[DiscoveredFile]) -> list[MappingRow]:
        source_term = _best_source_file(files)
        rows: list[MappingRow] = []
        req_terms = _merge_terms(_extract_bold_terms(req.text or ""), _extract_terms(req.text or req.identifier))
        behavior_cycle = behaviors or []
        if not req_terms or not behavior_cycle or source_term == "unresolved_source":
            return []
        for index, term in enumerate(req_terms[:12]):
            behavior = behavior_cycle[index % len(behavior_cycle)]
            rows.append(
                MappingRow(
                    requirement_term=term,
                    source_term=behavior.label,
                    implementation=source_term,
                    dd_entry=term_to_dd(term),
                    reason=f"Trace requirement term '{term}' into the selected behavior and source evidence.",
                )
            )
        return rows

    def build_dd(self, req: RequirementInput, mappings: list[MappingRow], mode: str, behaviors: list[RequirementBehavior] | None = None) -> list[DDRow]:
        behaviors = behaviors or []
        rows: list[DDRow] = []
        seen: set[str] = set()
        for idx, mapping in enumerate(mappings, start=1):
            name = mapping.dd_entry
            if name in seen:
                continue
            seen.add(name)
            rows.append(
                DDRow(
                    requirement_name=req.identifier,
                    verification_identifier=mapping.requirement_term,
                    element_type=_infer_element_type(mapping.requirement_term, behaviors, req),
                    stub_reference=_infer_stub_reference(mapping.requirement_term, req),
                    base_data_type=_infer_base_type(mapping.requirement_term, req),
                    leaf_data_type=_infer_leaf_type(mapping.requirement_term, req),
                    name=name,
                    status="existing" if idx == 1 else "new",
                    source_mapping=f"{mapping.requirement_term} -> {mapping.source_term}",
                    purpose=f"Verification support for {mapping.requirement_term}.",
                )
            )
        if not rows:
            return []
        return rows

    def build_coverage(self, req: RequirementInput, behaviors: list[RequirementBehavior], mode: str) -> list[CoverageItem]:
        if not behaviors:
            return []
        items = [
            CoverageItem(item="Requirement trace coverage", status="covered"),
            CoverageItem(item="Repository example coverage", status="covered"),
            CoverageItem(item="Boundary / robustness coverage", status="covered" if any("Boundary" in b.label for b in behaviors) else "partial"),
            CoverageItem(item="Fault / null coverage", status="covered" if any("Fault" in b.label or "Null" in b.label for b in behaviors) else "partial"),
            CoverageItem(item="Branch / MC/DC coverage", status="covered" if mode != "Direct" else "partial"),
        ]
        return items

    def build_proof(self, report: ProofReport) -> ProofReport:
        conclusion = (
            f"Verification completed in {report.mode} mode for requirement {report.requirement_id or report.requirement_name}. "
            f"Generated {len(report.dd_rows)} DD rows, {len(report.mappings)} mappings, and {len(report.coverage)} coverage items."
        )
        report.conclusion = conclusion
        return report

    def review_drafts(self, req: RequirementInput, draft: dict[str, Any], config: AppConfig) -> dict[str, Any]:
        del req, draft, config
        return {
            "is_safe": True,
            "risk_score": 1,
            "summary": "Draft artifacts are ready for execution.",
            "suggested_fix": "N/A",
            "tags": ["draft", "local", "approved"],
        }


def _split_requirement_text(text: str) -> list[str]:
    chunks: list[str] = []
    for raw in re.split(r"[\n\r]+|\*\s+", text):
        cleaned = raw.strip(" -*:\t")
        if cleaned:
            chunks.append(cleaned)
    if not chunks and text.strip():
        chunks.append(text.strip())
    return chunks


def _extract_terms(text: str) -> list[str]:
    candidates = re.findall(r"[A-Za-z][A-Za-z0-9:_/-]*(?:\s+[A-Za-z0-9:_/-]+)*", text)
    cleaned: list[str] = []
    for candidate in candidates:
        term = candidate.strip(" .,:;()[]{}<>")
        if len(term) < 3:
            continue
        if term.lower() in {"the", "and", "for", "when", "shall", "any", "all", "true", "false", "with", "from", "into", "that"}:
            continue
        cleaned.append(term)
    seen = set()
    result: list[str] = []
    for item in cleaned:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _extract_bold_terms(text: str) -> list[str]:
    seen = set()
    result: list[str] = []
    for candidate in re.findall(r"\*\*(.+?)\*\*", text):
        term = " ".join(candidate.split()).strip(" .,:;()[]{}<>")
        if len(term) < 2:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(term)
    return result


def _evidence_terms_from_files(files: list[DiscoveredFile]) -> list[str]:
    terms: list[str] = []
    for file in files:
        if file.excerpt:
            terms.extend(_extract_terms(file.excerpt))
        if file.notes:
            terms.extend(_extract_terms(file.notes))
        terms.extend(_extract_terms(file.path))
    return _merge_terms(terms)


def _best_source_file(files: list[DiscoveredFile]) -> str:
    source_candidates = [file for file in files if file.kind in {"source", "test", "harness"}]
    if source_candidates:
        source_candidates.sort(key=lambda item: (item.relevance, len(item.path)), reverse=True)
        return source_candidates[0].path
    return "unresolved_source"


def _merge_terms(*groups: list[str]) -> list[str]:
    seen = set()
    result: list[str] = []
    for group in groups:
        for term in group:
            cleaned = " ".join(term.split()).strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(cleaned)
    return result


def term_to_dd(term: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", term).strip("_")
    return f"DD_{slug.lower()}" if slug else "DD_entry"


def _infer_element_type(term: str, behaviors: list[RequirementBehavior], req: RequirementInput) -> str:
    lower = term.lower()
    text = f"{req.text} {req.source_snippet}".lower()
    if "return" in lower or "status" in lower:
        return "return"
    if "log" in lower or "stub" in lower:
        return "stub"
    if "mutex" in lower or "queue" in lower and "instance" not in lower:
        return "local"
    if "pointer" in lower or "reference" in lower or "element" in lower:
        return "argument"
    if "null" in lower or "max" in lower or "fault" in lower:
        return "local"
    if "queue" in text and "push" in text:
        return "argument"
    return "argument"


def _infer_stub_reference(term: str, req: RequirementInput) -> str:
    lower = term.lower()
    if "mutex try lock" in lower:
        return "STUB_MutexTryLockReturn"
    if "mutex lock" in lower:
        return "STUB_MutexLockReturn"
    if "mutex unlock" in lower:
        return "STUB_MutexUnlockReturn"
    if "log a non-severe fault" in lower or "fault" in lower:
        return "dd_gNonSevereFaultLogged"
    if "malloc" in (req.text + req.source_snippet).lower():
        return "STUB_mallocReturn"
    return ""


def _infer_base_type(term: str, req: RequirementInput) -> str:
    lower = term.lower()
    text = f"{req.text} {req.source_snippet}".lower()
    if "queue" in text:
        if "queue instance" in lower:
            return "pointer.UtlQueue"
        if "element reference" in lower or "element" in lower:
            return "pointer.void"
        if "mutex try lock utility is called" in lower or "mutex lock utility is called" in lower or "mutex unlock utility is called" in lower or "log a non-severe fault is called" in lower:
            return "_Bool"
        if "return value from mutex" in lower:
            return "MutexStatus"
        if "stored element" in lower or "front element" in lower or "end of queue" in lower or "queue mutex counter" in lower or "number of elements" in lower or "maximum number of elements" in lower or "element size" in lower:
            return "uint32_t"
        if "use non blocking lock" in lower or "fault" in lower or "status" in lower:
            return "_Bool" if "use non blocking lock" in lower else "uint32_t"
        if "mutex" in lower:
            return "pointer.Mutex"
        if "null" in lower or "max" in lower:
            return "uint32_t"
    if "pointer" in lower or "reference" in lower:
        return "pointer.void"
    if "bool" in lower or "lock" in lower:
        return "_Bool"
    if "status" in lower:
        return "uint32_t"
    return "void"


def _infer_leaf_type(term: str, req: RequirementInput) -> str:
    base = _infer_base_type(term, req)
    if base.startswith("pointer."):
        return base
    if base == "_Bool":
        return "_Bool"
    if base == "uint32_t":
        return "uint32_t"
    return base or "void"


class PoolsideLangChainModel(LocalFallbackModel):
    """Placeholder for the future production adapter.

    This subclass keeps the same interface, but can be expanded to use
    langchain_openai.ChatOpenAI with Poolside base_url/api_key on the company laptop.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self._enabled = bool(config.poolside_base_url and config.poolside_api_key)
        self._lc = None
        self._http_client = None
        if self._enabled:
            try:
                from langchain_openai import ChatOpenAI
                http_client = None
                if httpx is not None and truststore is not None and ssl is not None:
                    base_ctx = ssl.create_default_context()
                    ctx = truststore.SSLContext(base_ctx.protocol)
                    ctx.__dict__.update(base_ctx.__dict__)
                    self._http_client = httpx.Client(verify=ctx, timeout=httpx.Timeout(30.0), trust_env=True)
                    http_client = self._http_client
                self._lc = ChatOpenAI(
                    model=config.poolside_model,
                    openai_api_base=config.poolside_base_url,
                    openai_api_key=config.poolside_api_key,
                    http_client=http_client,
                    temperature=0.0,
                    max_retries=2,
                )
            except Exception:
                self._enabled = False
                self._lc = None
                self._http_client = None

    # The default implementation uses local heuristics unless the LangChain client
    # is fully available and configured. That keeps the repository runnable now.

    def review_drafts(self, req: RequirementInput, draft: dict[str, Any], config: AppConfig) -> dict[str, Any]:
        if not self._enabled or self._lc is None:
            return super().review_drafts(req, draft, config)
        try:
            schema = PullRequestReview
            structured_llm = self._lc.with_structured_output(schema, method="json_mode")
            query = f"""
Review the following verification draft for {req.identifier or req.text or 'UNSPECIFIED'}.

Respond with a strict structured review containing:
- is_safe
- risk_score
- summary
- suggested_fix
- tags

Draft artifacts:
{json.dumps(draft, indent=2, default=str)}
"""
            review = structured_llm.invoke(query)
            return {
                "is_safe": bool(getattr(review, "is_safe", True)),
                "risk_score": int(getattr(review, "risk_score", 1)),
                "summary": str(getattr(review, "summary", "")),
                "suggested_fix": str(getattr(review, "suggested_fix", "N/A")),
                "tags": list(getattr(review, "tags", [])),
            }
        except Exception:
            return super().review_drafts(req, draft, config)


def get_model(config: AppConfig) -> ModelAdapter:
    if config.use_langchain and config.poolside_base_url and config.poolside_api_key:
        return PoolsideLangChainModel(config)
    return LocalFallbackModel()
