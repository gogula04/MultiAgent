# Verification Rules

## Core Principles

- Deterministic output only.
- No random elements.
- No timestamps in generated artifacts.
- No external state in the generated result.
- Existing repo examples are style references, not blockers.
- Do not guess mappings, expected values, or coverage cases.
- Do not modify production code.
- Any older prompt bundle used by a removed testbot is fallback reference only; keep the active path deterministic and code-driven unless the task explicitly says to restore legacy extraction.

## Schema Compliance

- Follow `.devcontainer/rbtca_schema.yaml` exactly.
- Use the expected key names and ordering for RBTCA output.
- Keep RBTCA test-case IDs and Python test names aligned.
- One Python test function per RBTCA reference unless a case intentionally covers multiple scenarios.

## Implementation File Usage

Only read implementation/source files in these cases:

1. Creating or updating a Hybrid `.rvstest` procedure vector.
2. Debugging a failing generated test or other blocked verification path.
3. Resolving a mapping failure when requirement text, headers, and dictionaries do not provide enough evidence.

Do not read implementation files for simple Direct-method work, normal artifact generation, or style/reference lookup, and do not modify production source code.

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
