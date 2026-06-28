# Verification Rules

## Core Principles

- Deterministic output only.
- No random elements.
- No timestamps in generated artifacts.
- No external state in the generated result.
- Existing repo examples are style references, not blockers.
- Do not guess mappings, expected values, or coverage cases.
- Do not modify production code.
- Any older prompt bundle used by a removed legacy harness is fallback reference only; use it only when the deterministic requirement extractor leaves gaps in classification, IO variables, expressions, math, or formatting.

## Schema Compliance

- Follow `.devcontainer/rbtca_schema.yaml` exactly.
- Use the expected key names and ordering for RBTCA output.
- Keep RBTCA test-case IDs and Python test names aligned.
- One Python test function per RBTCA reference unless a case intentionally covers multiple scenarios.

## Implementation File Usage

Only read implementation/source files in these cases:

1. Creating or updating a Direct or Hybrid verification artifact when exact visible constants, literal values, range limits, boundary values, or comparison constraints are needed for test generation.
2. Debugging a failing generated test or other blocked verification path.
3. Review-stage inspection of the generated verification bundle.
4. Resolving a mapping failure when requirement text, headers, and dictionaries do not provide enough evidence.
5. Extracting visible constants, exact literal values, range limits, boundary values, or comparison constraints needed for verification when one of the allowed cases above applies.
6. Using the legacy extraction prompts as fallback for requirement classification, IO extraction, expression extraction, math extraction, or format extraction when the deterministic parser cannot prove the result safely.

Do not read implementation files for simple non-artifact Direct work, normal evidence collection, or style/reference lookup, and do not modify production source code.
Do not read implementation files during requirement extraction, evidence collection, normalization, analysis, strategy, or any artifact generation that does not need proven source constants or constraints.

## Blockers

Block only when one of these is true:

- the requirement text cannot be located
- source or header mapping cannot be proven
- DD/UUT/RVS mapping cannot be created from evidence
- the expected behavior cannot be determined safely
- there is no executable verification path
- the remaining evidence still does not support safe progress after direct text/header/dictionary checks

## Data Type Handling

- Unknown numeric type defaults to `Float` only as a last resort.
- Flatten structs to field-level variables.
- Test arrays at first element, last element, and boundary conditions.
- Test enumerations across all valid values plus out-of-range behavior when required.
- Test pointers with valid and null values.

## Verification Discipline

- Existing repo pattern wins only when it is evidence-backed and compatible.
- If something is unclear, leave it missing rather than guessing.
- Use implementation/source code only after the non-implementation evidence is exhausted and one of the allowed exception paths applies.
- After generation, verify the RBTCA structure, the case count, and the traceability between artifacts.

## C/C++ Support

- Supported: C and C++ headers, source files, free functions, class methods, structs, enums, globals, and named constants when they appear as visible symbols.
- Supported best-effort: namespaces, overloads, `Class::Method` names, and template-heavy code when the symbol is still visible in headers or source.
- Not guaranteed: full C++ semantic parsing, macro-expanded behavior, anonymous internals, or deep template/metaprogramming reasoning.
- If a C/C++ symbol cannot be proven from requirement text, headers, dictionaries, or allowed implementation evidence, block or debug instead of guessing.
