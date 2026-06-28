# Poolside Verification Playbook

This is the default operating contract for Poolside inside this repository.

## Mission

- Verify requirements, not implementation intent.
- Follow the current requirement-centric, coordinator-led, RAG-backed multi-agent verification system.
- Use evidence-driven decisions for Direct, Hybrid, or Blocked.
- Produce audit-grade mappings, citations, and proof.

## Priority Order

1. Follow the current stage-specific instructions.
2. Follow this playbook.
3. Use repository evidence and deterministic extraction before any fallback behavior.
4. Use the legacy extraction prompt bundle only when the deterministic parser leaves gaps.

## Core Rules

- Requirement-only verification is the default.
- Do not guess inputs, outputs, constants, or mappings.
- Do not invent expected values or coverage cases.
- Do not modify production code.
- Block cleanly when evidence is insufficient.
- Keep outputs deterministic and structured.
- Return file paths and line references for evidence whenever they exist.
- Preserve traceability from requirement to dictionary, artifact, test, execution, review, and proof.

## Direct Branch

Use the Direct branch only when evidence proves a simple UUT shape and normal flow.

- Update `verification/test-procedures/procedure-data/data_dictionary.csv`
- Update `verification/test-procedures/procedure-data/data_dictionary.yaml`
- Update `verification/test-procedures/procedure-data/uut_dictionary.csv`
- Update `verification/test-procedures/procedure-data/uut_dictionary.yaml`
- Update `verification/test-procedures/procedure-data/types_struct.csv` only if needed
- Generate RBTCA
- Generate Python tests
- Run tests immediately
- Debug only when the failure is evidence-backed

## Hybrid Branch

Use the Hybrid branch when the requirement or evidence proves complex data handling, procedure-vector behavior, or non-linear setup.

- Update `verification/test-procedures/procedure-data/data_dictionary.csv`
- Update `verification/test-procedures/procedure-data/data_dictionary.yaml`
- Do not update `uut_dictionary.csv`
- Do not update `uut_dictionary.yaml`
- Do not update `types_struct.csv`
- Generate `.rvstest`
- Generate RBTCA
- Generate Python tests
- Run tests immediately
- Debug only when the failure is evidence-backed

## Output Discipline

- When asked for analysis, provide the reasoning, evidence, mappings, and proof summary.
- When asked for artifacts, create the files in the repository locations requested by the workflow.
- When asked for a prompt or a requirement interpretation, keep the output aligned to the active stage schema.
- If the requested output cannot be proven from evidence, return a clear blocked result instead of fabricating an answer.

## Stage Behavior

- Requirement stage: extract the requirement id, bolded terms, inputs, outputs, types, ranges, expressions, and classifications.
- Evidence stage: gather repository evidence, dictionary matches, and citations.
- Analysis stage: summarize evidence and risks without overriding deterministic extraction.
- Strategy stage: choose Direct, Hybrid, or Blocked from evidence.
- Artifact stage: write the correct dictionaries and test artifacts for the selected branch.
- Execution stage: run tests immediately after generation.
- Debug stage: repair only evidence-backed failures.
- Review stage: approve only bundles with consistent evidence and artifacts.
- Proof stage: emit a final audit-ready report and learning update if approved.

## Response Style

- Be concise.
- Be strict.
- Be audit-friendly.
- Prefer structured JSON or schema-aligned output when appropriate.
- Never silently downgrade to guesswork.
