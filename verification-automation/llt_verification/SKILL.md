---
name: llt-verification
description: Requirement-centric, coordinator-led, RAG-backed multi-agent verification system with controlled offline learning, tenant-scoped enterprise queueing, and approval-gated evidence access.
metadata:
  short-description: End-to-end requirement verification
---

# LLT Verification Agent

Use this skill when the user asks to verify a requirement, especially with a prompt like `verify requirement FAF-LLR-401`.
This skill is the trigger and guardrail layer. The execution engine lives in the agent runtime, Poolside is the only backend, and the detailed flow lives in [references/flow.md](references/flow.md).

## What To Do

- Technical stack: Poolside `laguna_m_fp8_fp8kv_re_04_2026`, local HuggingFace `BAAI/bge-m3` for dense retrieval, FAISS, and LangChain/HuggingFace integration.
- The runtime is coordinator-led and multi-agent based: coordinator, requirement, evidence, normalization, analysis, strategy, direct artifact, hybrid artifact, traceability, execution, debug, review, and proof stages.
- The requirement stage is allowed to use the legacy extraction prompt bundle only as a fallback when the deterministic parser leaves gaps.
- Requirement-only verification is the default mode.
- Implementation/source reads are blocked unless the exception gate is explicitly approved.
- Approved runs may be learned offline only when `LLT_AUTO_LEARNING_APPROVED=1` is set.
- Learned cases must come only from passed proof reports and approved reviews.
- Reuse candidates should only surface when their similarity score clears the learned threshold and confidence gate.
- Use `--replay-learning-case` or `--replay-learning-evals` to evaluate approved learned cases offline without recursive learning.
- Enterprise mode is available through `--tenant-id`, `--user-role`, `--submit-job`, `--approve-job`, `--run-queue`, `--enterprise-dashboard`, and `--enterprise-regression-evals`.
- Existing repo examples are style guides, not blockers.
- Do not invent DD/UUT mappings, expected values, or coverage cases.
- Generate RBTCA before Python tests.
- Keep Python test IDs and RBTCA test-case IDs aligned 1:1.
- Any old prompt bundle or prompt-engineering asset is fallback reference only; use it only when the deterministic requirement extractor leaves gaps in classification, IO variables, expressions, math, or formatting.
- The evidence layer must use requirement text, source files, and repository CSV/YAML dictionaries such as `function.csv`, `enum.csv`, and the procedure-data dictionaries when they exist, and every retrieved hit should carry a file path and line reference.
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
- Agent CLI: `python llt_verification_agent.py --replay-learning-case FAF-LLR-401-20260627T120000Z`
- Agent CLI: `python llt_verification_agent.py --replay-learning-evals`
- Agent CLI: `python llt_verification_agent.py --submit-job "verify requirement FAF-LLR-401"`
- Agent CLI: `python llt_verification_agent.py --approve-job job-20260627-0001`
- Agent CLI: `python llt_verification_agent.py --run-queue`
- Agent CLI: `python llt_verification_agent.py --enterprise-dashboard`
- Agent CLI: `python llt_verification_agent.py --enterprise-regression-evals`
- Inspect/testability: `python llt_evaluator.py --step2 FAF-LLR-401`
- RBTCA only: `python llt_evaluator.py --generate-rbtca FAF-LLR-401`
- Test only: `python llt_evaluator.py --generate-test FAF-LLR-401`
- Poolside wiring: set `POOLSIDE_BASE_URL`, `POOLSIDE_API_KEY`, `POOLSIDE_AGENT_MODEL`, and optionally `POOLSIDE_AGENT_NAME` before running the agent runtime
- Implementation access approval: set `LLT_IMPLEMENTATION_READ_APPROVED=1` or pass `--allow-implementation-reads` only when an approved exception allows source reads

## Workflow

1. Index the repo with `python llt_verification_agent.py --index`.
2. Use `python llt_verification_agent.py --query "verify requirement FAF-LLR-401"` or `python llt_verification_agent.py --interactive` for RAG-backed repo questions.
3. Use `python llt_verification_agent.py --verify "verify requirement FAF-LLR-401"` for the full verification workflow.
4. Follow [references/flow.md](references/flow.md) for the multi-agent architecture and execution flow.
5. Follow [references/policy.md](references/policy.md) for allowed evidence sources and approval gates.
6. Use [references/verification-rules.md](references/verification-rules.md) for evidence, blocker, and implementation-read guardrails.
7. Use [references/test-selection.md](references/test-selection.md) for Direct vs Hybrid selection and case choice.
8. Use [references/trigger-tests.md](references/trigger-tests.md) to validate activation against positive and near-miss prompts.
9. Use `evals/evals.json` for repeatable trigger evaluation.
10. Return the proof report in [references/report-format.md](references/report-format.md).
