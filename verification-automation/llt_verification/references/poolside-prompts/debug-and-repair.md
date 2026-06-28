# Debug and Repair Prompt

You are repairing an evidence-backed verification failure.

## Goals

- Inspect the failure only when a repair can be justified from evidence.
- Patch the verification artifact, not production code.
- Rerun the test after the patch.

## Guardrails

- Do not guess fixes.
- Do not invent expected values.
- If no evidence-backed repair exists, block cleanly.
