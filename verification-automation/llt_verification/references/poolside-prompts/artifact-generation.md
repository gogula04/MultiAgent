# Artifact Generation Prompt

You are generating verification artifacts for a selected branch.

## Goals

- Use the approved method decision.
- Produce the exact dictionaries and test artifacts required by the branch.
- Keep artifact names and mappings traceable.

## Direct Branch

- Update `data_dictionary.csv`
- Update `data_dictionary.yaml`
- Update `uut_dictionary.csv`
- Update `uut_dictionary.yaml`
- Update `types_struct.csv` only if needed
- Generate RBTCA
- Generate Python tests

## Hybrid Branch

- Update `data_dictionary.csv`
- Update `data_dictionary.yaml`
- Generate `.rvstest`
- Generate RBTCA
- Generate Python tests

## Guardrails

- Never invent expected values.
- Never skip required dictionary updates.
- If evidence is insufficient, return blocked instead of fabricating artifacts.
