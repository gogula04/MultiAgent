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
10. Final pass, fail, or blocked status

## Reporting Rules

- Include the exact requirement ID when one was provided.
- Include the exact command and exit code for each execution step.
- Do not claim pass unless the command actually passed.
- If blocked, name the blocker and the evidence that proves it.
- If the legacy extraction prompts were used, name the prompt files that fired and which gaps they filled.
- Keep the report concise but complete enough to audit.
