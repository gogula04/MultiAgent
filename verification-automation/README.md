# Verification Automation

Multi-agent verification automation for HLT and LLT workflows.

This project is designed to verify software requirements end to end using a
repo-aware multi-agent pipeline. It scans your company repository, resolves the
requirement text, maps bolded requirement terms to source and verification
artifacts, selects the right verification mode, generates drafts, waits for
review, executes tests, and produces evidence.

## What The Tool Does

The tool is built around a strict verification workflow:

1. Intake a requirement ID, name, or source snippet.
2. Discover repo evidence for the requirement.
3. Parse the requirement and extract bolded terms.
4. Map requirement terms to source, dictionaries, and verification data.
5. Select one of three verification modes:
   - Direct
   - Hybrid
   - Manual
6. Generate draft verification artifacts.
7. Present a human review gate.
8. Execute approved drafts.
9. Collect logs, coverage, and test evidence.
10. Produce proof and traceability output.

## Supported Verification Modes

### Direct
Use Direct when the requirement interface maps cleanly to the function signature.
It typically generates:

- `Data_dictionary.csv`
- `uut_dictionary.csv`
- Python testcases

### Hybrid
Use Hybrid when the verification needs RVSTest setup, pointer handling, stubs,
or internal helper control.
It typically generates:

- `Data_dictionary.csv`
- `verification.rvstest`
- Python testcases

### Manual
Use Manual when the verification must be driven directly by RVSTest vectors and
manual procedure control.
It typically generates:

- manual RVSTest procedures
- traceability notes
- supporting test evidence

## Key Capabilities

- Repo-backed requirement resolution from `requirements/HLR` and `requirements/LLR`
- Bolded-term extraction from requirement text
- Source + dictionary mapping into verification artifacts
- Strict blocking when a requirement cannot be resolved
- Draft artifact generation with a human review gate
- Execution and proof generation for approved drafts
- Failure triage with classification for setup, mapping, harness, source, ambiguity, and coverage gaps
- Poolside-ready configuration through environment variables
- LangChain/LangGraph-compatible orchestration
- Local fallback mode for development without company credentials

## Inputs The Tool Uses

- Requirement ID
- Requirement name
- Requirement text
- Source snippet
- Company repo root
- Data dictionaries
- Source code
- Existing test procedures and examples

## Outputs The Tool Can Generate

- `Data_dictionary.csv`
- `uut_dictionary.csv`
- `verification.rvstest`
- `test_requirement_generated.py`
- `traceability_notes.md`
- `rapita/rvsconfig.xml`
- `rapita/rapita-node-mapping.md`
- `proof_report.md`

## Strict Behavior

The tool does not fabricate verification results.

- If the requirement is not found, the run blocks.
- If the repo root is wrong, the run blocks.
- If there is not enough evidence to verify the requirement, the run blocks.
- If review is enabled and the draft is rejected, the workflow returns to draft generation.

## Repository Layout Assumptions

The tool expects the company repo to contain:

- `requirements/HLR`
- `requirements/LLR`
- `requirements/data_dictionary`
- `software/source`
- `verification/test-cases/high_level`
- `verification/test-cases/low_level`
- `verification/test-procedures`

## Poolside Configuration

When running in the company environment, set:

- `POOLSIDE_BASE_URL`
- `POOLSIDE_API_KEY`
- `POOLSIDE_MODEL`

Example:

```bash
export POOLSIDE_BASE_URL="https://poolside-col-web.xeta.rtx.com/openai/v1"
export POOLSIDE_API_KEY="ps-<your-key>"
export POOLSIDE_MODEL="edx-malibu-model-2-1"
```

## Web UI

Launch the local control room:

```bash
verification-automation-web --repo-root . --output-dir artifacts-web
```

Auto-run a requirement when the UI opens:

```bash
verification-automation-web \
  --repo-root . \
  --output-dir artifacts-web \
  --requirement "FAF-LLR-1323" \
  --text "The Push Element operation utility shall use Mutex Lock..." \
  --auto-run
```

The UI supports:

- requirement intake
- repo resolution summary
- Direct / Hybrid / Manual mode selection
- mapping traceability preview
- draft artifact review
- execution and coverage summary
- proof and evidence display

## CLI

Run the pipeline without the UI:

```bash
verification-automation "FAF-LLR-1323" \
  --repo-root /workspaces/foundations-and-framework \
  --text "The Push Element operation utility shall use Mutex Lock..." \
  --mode Auto
```

## Docker

Build and run the packaged container:

```bash
docker build -t verification-automation .
docker run --rm -p 8787:8787 verification-automation
```

The container starts the same UI entrypoint on port `8787`.

## Architecture

The full workflow diagram is documented in [`articture.md`](./articture.md).
