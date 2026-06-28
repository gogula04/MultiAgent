# Verification Policy

## Default Mode

- Requirement-only verification is the default operating mode.
- The system should prefer requirement text, dictionaries, approved verification docs, and traceability artifacts.
- Implementation/source reads are blocked unless an explicit exception approval is granted.

## Allowed Evidence Sources

- Requirement text and extracted requirement structure
- Requirement documents
- `data_dictionary.csv`
- `data_dictionary.yaml`
- `uut_dictionary.csv`
- `uut_dictionary.yaml`
- Approved verification documents and prior traceability artifacts

## Exception-Gated Sources

- Header files
- Source files
- Visible source symbols
- Any implementation-derived constants, constraints, or literal values

These sources may only be used when the run has explicit exception approval, such as
`LLT_IMPLEMENTATION_READ_APPROVED=1` or the `--allow-implementation-reads` flag.

## Audit and Traceability

- Every stage must emit an audit trail entry.
- Every run must produce a manifest and proof report.
- Every generated artifact should be traceable back to the requirement and evidence used.

## Enterprise Controls

- Queue submission is tenant-scoped and RBAC-gated.
- Job approval and queue execution require privileged roles.
- Dashboard, metrics, and regression outputs are written per tenant.
- Regression results must cover activation, retrieval, selection, and proof quality.

## Controlled Auto-Learning

- Approved verification runs may be stored as structured learning cases only when the auto-learning gate is explicitly enabled.
- The auto-learning gate is controlled by `LLT_AUTO_LEARNING_APPROVED=1`.
- Only runs with a passed proof report and approved review may be learned.
- Failed, blocked, or unverified runs must never be added to the learning store.
- Learning updates are offline only: learned cases, derived evals, templates, and retrieval indexes are written locally and do not change policy.
- Reuse candidates must clear an explicit similarity threshold before they are shown as recommended.
- The replay path must run without enabling recursive learning so approved cases can be evaluated safely offline.
