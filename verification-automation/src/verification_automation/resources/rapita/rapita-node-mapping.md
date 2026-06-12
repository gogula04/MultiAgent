# Rapita XML to Multi-Agent Mapping

This reference maps the canonical `rvsconfig.xml` sections to the verification automation agents used by the tool.

| XML section | Purpose | Multi-agent node | Tool output / evidence |
| --- | --- | --- | --- |
| `<project>` | Identifies project identity, languages, environment variables, and integration recipe wiring. | Requirement Intake Agent + Repo Discovery Agent | Project metadata, repo-root derived paths, and verification scope. |
| `<environment>` | Declares data dictionary path, tests folder, project name, and PATH setup. | Source + Dictionary Mapping Agent | Data dictionary location, procedure location, and execution environment. |
| `<integration-recipes>` | Describes validation/build recipe stages. | Verification Strategy Agent + Direct/Hybrid/Manual Builder | Selected verification mode and build-stage contract. |
| `<integrations>` | Declares target-specific coverage integration settings. | Test Execution Agent + Coverage Analyzer Agent | Execution target, coverage collection, and export strategy. |
| `<analysis>` | Declares the coverage analysis profile. | Coverage Analyzer Agent | Coverage profile evidence used by the proof package. |
| `<targets>` | Declares clean/build/run commands and instrumentation behavior. | Test Execution Agent + Failure Triage Agent | Exact commands and target selection for execution. |
| `<exports>` | Declares output report formats and filenames. | Proof & Traceability Reporter | XML/JUnit/TXT export evidence for tests and coverage. |
| `<testframework>` | Declares the procedures folder used by the test runner. | Repo Discovery Agent + Harness/RVSTest Builder | Procedure discovery and harness location evidence. |

## Notes

- The generated automation bundle writes a copy of the canonical `rvsconfig.xml` to `artifacts/rapita/rvsconfig.xml`.
- The bundle also writes this mapping note to `artifacts/rapita/rapita-node-mapping.md`.
- The repository-specific locations are derived from the project structure under `requirements/`, `software/`, and `verification/`.

## Repository Anchors

- Requirements: `requirements/HLR` and `requirements/LLR`
- Data dictionaries: `requirements/data_dictionary`
- Source: `software/source`
- Test cases: `verification/test-cases`
- Procedures: `verification/test-procedures`
