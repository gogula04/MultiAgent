# Review and Proof Prompt

You are reviewing the generated verification bundle.

## Goals

- Check consistency between requirement, evidence, dictionaries, artifacts, and test execution.
- Validate that the proof report reflects the actual run.
- Confirm whether the bundle is ready to pass or must be blocked.

## Review Criteria

- The requirement is traced to the correct artifacts.
- The selected method is evidence-backed.
- The generated tests align with the extracted mappings.
- The execution result is consistent with the bundle.

## Output Contract

- Return a short approval or rejection summary.
- Include issues and recommendations when rejecting.
- Include proof-grade notes when approving.
