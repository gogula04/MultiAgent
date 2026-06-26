---
name: llt-verification
description: For new LLT requirement verification, trigger on prompts like "verify requirement FAF-LLR-123", "verify requirement REQID", or pasted requirement text; then locate the requirement, choose Direct or Hybrid from evidence, generate RBTCA and pytest_smart artifacts, run them, debug failures, and return proof.
metadata:
  short-description: End-to-end requirement verification
---

# LLT Verification

Use this skill when the user asks to verify a requirement, especially with a prompt like `verify requirement REQID`.
Load the detailed flow and guardrails only after activation.

## What To Do

- Existing repo examples are style guides, not blockers.
- Do not invent DD/UUT mappings, expected values, or coverage cases.
- Generate RBTCA before Python tests.
- Keep Python test IDs and RBTCA test-case IDs aligned 1:1.
- Any old prompt bundle or prompt-engineering asset is fallback reference only; do not depend on it for the main verification path unless you are explicitly restoring legacy extraction behavior.
- For C and C++, work from visible headers/source symbols such as free functions, class methods, structs, enums, globals, and named constants; do not guess beyond what can be proven.
- Only read implementation/source files in these exception paths:
  - creating or updating a Hybrid `.rvstest` procedure vector
  - debugging a failing test or other blocked/failed verification path
  - resolving a mapping failure when evidence cannot be proven from requirement text, headers, or dictionaries alone
- For Direct work and normal mapping, use requirement text, headers, dictionaries, and examples only.
- Never modify production code.
- If a case is coverage-only and cannot execute, mark it skipped with a reason.
- Use the trigger matrix in `scripts/trigger_matrix.py` and `references/trigger-tests.md` after description edits.
- Use `evals/evals.json` as the canonical activation test set.

## Entry Points

- Full flow: `python autonomous_verifier.py FAF-LLR-401`
- Inspect/testability: `python llt_verification.py --step2 FAF-LLR-401`
- RBTCA only: `python llt_verification.py --generate-rbtca FAF-LLR-401`
- Test only: `python llt_verification.py --generate-test FAF-LLR-401`
- Batch coverage: `python batch_verify.py`

## Workflow

1. Follow [references/flow.md](references/flow.md) for the end-to-end sequence.
2. Use [references/verification-rules.md](references/verification-rules.md) for evidence, blocker, and implementation-read guardrails.
3. Use [references/test-selection.md](references/test-selection.md) for Direct vs Hybrid selection and case choice.
4. Use [references/trigger-tests.md](references/trigger-tests.md) to validate activation against positive and near-miss prompts.
5. Use `evals/evals.json` for repeatable trigger evaluation.
6. Return the proof report in [references/report-format.md](references/report-format.md).
