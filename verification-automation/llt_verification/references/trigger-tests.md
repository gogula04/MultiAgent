# Trigger Tests

Use these prompts to validate that the skill activates only for requirement-verification work.

## Positive Prompts

- `verify requirement FAF-LLR-401`
- `verify requirement FAF-LLR-123`
- `verify requirement REQID`
- `verify FAF-LLR-401 end to end`
- `verify requirement FAF-LLR-401 and generate proof`
- `verify this requirement: FAF-LLR-401`

Expected: the LLT Verification skill activates.

These prompts are for activation testing only; the actual verification flow still runs through the Poolside-only peer-agent runtime and may use the legacy extraction prompts only as fallback parsing helpers.

## Near Miss Prompts

- `analyze requirement FAF-LLR-401`
- `summarize FAF-LLR-401`
- `review this requirement`
- `run tests for FAF-LLR-401`
- `explain FAF-LLR-401`
- `verify my code`

Expected: the skill should not be the primary activation target.

## Manual Check

1. Open `/skills` in Poolside Agent mode.
2. Confirm `LLT Verification` appears in the list.
3. Try one positive prompt and confirm activation.
4. Try one near-miss prompt and confirm a different skill or no skill activates.
5. Repeat after every description change.
