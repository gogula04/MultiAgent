# Verification Automation

Multi-agent verification automation for HLT and LLT workflows.

This repository is scaffolded to run locally first, then accept Poolside
configuration on a company machine via environment variables:

- `POOLSIDE_BASE_URL`
- `POOLSIDE_API_KEY`
- `POOLSIDE_MODEL`

The orchestration layer is designed to be compatible with LangChain/LangGraph,
while the repo-local fallback keeps the workflow runnable without external
credentials.

Generated artifacts include:

- `Data_dictionary.csv`
- `uut_dictionary.csv` for Direct mode
- `verification.rvstest` for Hybrid / Manual mode
- `test_requirement_generated.py`
- `traceability_notes.md`
- `rapita/rvsconfig.xml`
- `rapita/rapita-node-mapping.md`
- `proof_report.md`

Rapita execution is driven by the canonical configuration template in
`templates/rapita/rvsconfig.xml` and the XML-to-agent mapping note in
`docs/rapita-node-mapping.md`.

## Web UI

Launch the local control room with one command:

```bash
verification-automation-web --repo-root . --output-dir artifacts-web
```

To auto-run a requirement when the UI opens:

```bash
verification-automation-web \
  --repo-root . \
  --output-dir artifacts-web \
  --requirement "FAF-LLR-1323" \
  --text "The Push Element operation utility shall use Mutex Lock..." \
  --auto-run
```

## Docker

Build and run the packaged container:

```bash
docker build -t verification-automation .
docker run --rm -p 8787:8787 verification-automation
```

The container starts the same UI entrypoint on port `8787`.
