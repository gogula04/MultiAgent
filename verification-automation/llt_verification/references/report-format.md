# Proof Report Format

Return the final result in this order:

1. Requirement mapping
2. Source mapping
3. DD/UUT/RVS mapping
4. Method decision
5. RBTCA to Python mapping
6. Files created or modified
7. Commands run
8. Test results
9. Failure analysis if anything failed
10. Learning result if auto-learning was approved
11. Final pass, fail, or blocked status

## Current System Context

- The proof report is the audit-facing output of a requirement-centric, coordinator-led, RAG-backed multi-agent verification system.
- The report must reflect the current runtime behavior, including controlled offline learning, tenant-scoped enterprise queueing, and approval-gated evidence access.
- If the run came through the enterprise control plane, include the tenant ID, job ID, approval status, queue status, and async execution result when available.

## Reporting Rules

- Include the exact requirement ID when one was provided.
- Include the exact command and exit code for each execution step.
- Do not claim pass unless the command actually passed.
- If blocked, name the blocker and the evidence that proves it.
- If the legacy extraction prompts were used, name the prompt files that fired and which gaps they filled.
- If auto-learning was enabled, include the learned-case file, derived eval file, and index update status.
- If a reuse candidate was used, include its score and confidence label.
- If a replay command was used, include the replayed case ID and replay status.
- If an enterprise job was used, include the tenant-scoped dashboard or regression artifact references when they were generated.
- Keep the report concise but complete enough to audit.
