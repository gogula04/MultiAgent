---
name: llt-verification
description: Skill-guided, repo-aware LLT verification agent for prompts like "verify requirement FAF-LLR-123", "verify requirement REQID", or pasted requirement text; uses a Poolside-only peer-agent pipeline to locate the requirement, extract and classify it, gather repo evidence, choose Direct or Hybrid from evidence, generate verification artifacts, run them, debug failures, review the bundle, and return proof.
metadata:
  short-description: End-to-end requirement verification
---

# LLT Verification Agent

Use this skill when the user asks to verify a requirement, especially with a prompt like `verify requirement REQID`.
This skill is the trigger and guardrail layer. The execution engine lives in the agent runtime, Poolside is the only backend, and the detailed flow lives in [references/flow.md](references/flow.md).

## What To Do

- Technical stack: Poolside `laguna_m_fp8_fp8kv_re_04_2026`, local HuggingFace `BAAI/bge-m3` for dense retrieval, FAISS, and LangChain/HuggingFace integration.
- The runtime is peer-agent based: coordinator, requirement, evidence, normalization, analysis, strategy, direct artifact, hybrid artifact, traceability, execution, debug, review, and proof stages.
- The requirement stage is allowed to use the legacy extraction prompt bundle only as a fallback when the deterministic parser leaves gaps.
- Existing repo examples are style guides, not blockers.
- Do not invent DD/UUT mappings, expected values, or coverage cases.
- Generate RBTCA before Python tests.
- Keep Python test IDs and RBTCA test-case IDs aligned 1:1.
- Any old prompt bundle or prompt-engineering asset is fallback reference only; use it only when the deterministic requirement extractor leaves gaps in classification, IO variables, expressions, math, or formatting.
- The evidence layer must use requirement text, source files, and repository CSV dictionaries such as `function.csv`, `enum.csv`, and the procedure-data dictionaries when they exist.
- For C and C++, work from visible headers/source symbols such as free functions, class methods, structs, enums, globals, and named constants; do not guess beyond what can be proven.
- Only read implementation/source files in these exception paths:
  - creating or updating a Direct or Hybrid artifact when exact visible constants, literal values, range limits, boundary values, or comparison constraints are needed for test generation
  - creating or updating a Hybrid `.rvstest` procedure vector
  - debugging a failing test or other blocked/failed verification path
  - review-stage inspection of the generated verification bundle
  - resolving a mapping failure when evidence cannot be proven from requirement text, headers, or dictionaries alone
- The legacy prompt bundle may also be used as a fallback inside requirement extraction when the parser cannot safely recover classification, IO variables, expressions, math, or format details from the requirement text alone.
- When those source reads are allowed, extract visible constants, exact literal values, range limits, boundary values, and comparison constraints so verification uses the exact proven numbers instead of guesses.
- For Direct evidence and normal mapping, use requirement text, headers, dictionaries, and examples only.
- Never modify production code.
- If a case is coverage-only and cannot execute, mark it skipped with a reason.
- Use the trigger matrix in `scripts/trigger_matrix.py` and `references/trigger-tests.md` after description edits.
- Use `evals/evals.json` as the canonical activation test set.

## Entry Points

- Agent CLI: `python llt_verification_agent.py --index`
- Agent CLI: `python llt_verification_agent.py "verify requirement FAF-LLR-401"`
- Agent CLI: `python llt_verification_agent.py --query "verify requirement FAF-LLR-401"`
- Agent CLI: `python llt_verification_agent.py --interactive`
- Agent CLI: `python llt_verification_agent.py --verify "verify requirement FAF-LLR-401"`
- Inspect/testability: `python llt_evaluator.py --step2 FAF-LLR-401`
- RBTCA only: `python llt_evaluator.py --generate-rbtca FAF-LLR-401`
- Test only: `python llt_evaluator.py --generate-test FAF-LLR-401`
- Poolside wiring: set `POOLSIDE_BASE_URL`, `POOLSIDE_API_KEY`, `POOLSIDE_AGENT_MODEL`, and optionally `POOLSIDE_AGENT_NAME` before running the agent runtime

## Workflow

1. Index the repo with `python llt_verification_agent.py --index`.
2. Use `python llt_verification_agent.py --query ...` or `--interactive` for RAG-backed repo questions.
3. Use `python llt_verification_agent.py --verify ...` for the full verification workflow.
4. Follow [references/flow.md](references/flow.md) for the peer-agent architecture and execution flow.
5. Use [references/verification-rules.md](references/verification-rules.md) for evidence, blocker, and implementation-read guardrails.
6. Use [references/test-selection.md](references/test-selection.md) for Direct vs Hybrid selection and case choice.
7. Use [references/trigger-tests.md](references/trigger-tests.md) to validate activation against positive and near-miss prompts.
8. Use `evals/evals.json` for repeatable trigger evaluation.
9. Return the proof report in [references/report-format.md](references/report-format.md).
