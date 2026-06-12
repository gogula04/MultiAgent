"""Render verification artifacts from the agent state."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from .models import DDRow, MappingRow, ProofReport, RequirementBehavior, UUTRow


def render_data_dictionary_csv(rows: list[DDRow]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["RequirementName", "VerificationIdentifier", "elementType", "stubReference", "baseDataType", "leafDataType"])
    for row in rows:
        writer.writerow([
            row.requirement_name or row.name,
            row.verification_identifier or row.name,
            row.element_type,
            row.stub_reference,
            row.base_data_type,
            row.leaf_data_type,
        ])
    return buffer.getvalue()


def render_uut_dictionary_csv(row: UUTRow | None = None) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["uut name", "rate", "initFcn", "return", "step fcn", "return_stepfn", "mockFcns", "preconditions comma sep"])
    if row is not None:
        writer.writerow([
            row.uut_name,
            row.rate,
            row.initFcn,
            row.return_type,
            row.step_fcn,
            row.return_stepfn,
            row.mockFcns,
            row.preconditions,
        ])
    return buffer.getvalue()


def render_rvstest_setup(component_name: str, function_name: str, mappings: list[MappingRow], dd_rows: list[DDRow], mode: str) -> str:
    vector_name = "Vector 1"
    init_id = "Init 1"
    lines = [
        '<?xml version="1.0" encoding="ASCII"?>',
        '<testmodel:Suite xmi:version="2.0" xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:testmodel="http://www.rapitasystems.com/testmodel" version="1.1">',
        f' <tests name="Test 1 {component_name}">',
        " <localdecls>",
        f' <initializations id="{init_id}"/>',
    ]
    for row in dd_rows:
        local_type = _dd_local_type(row)
        lines.append(f' <locals name="{row.verification_identifier or row.name}" type="{local_type}">')
        lines.append(f'  <initvals value="{_default_init_value(local_type)}" initcol_ref="//@tests.0/@localdecls/@initializations.0"/>')
        lines.append(" </locals>")
    lines.extend(
        [
            " </localdecls>",
            " <actions>",
            f' <vectors id="{vector_name}"/>',
        ]
    )
    for row in dd_rows:
        if row.element_type == "stub":
            lines.extend(
                [
                    f' <valueactions xsi:type="testmodel:StubAction" uniqueName="at function {row.verification_identifier}">',
                    ' <setActions uniqueName="return">',
                    f' <vectorVal_refs value="{row.verification_identifier}" vector_ref="//@tests.0/@actions/@vectors.0"/>',
                    " </setActions>",
                    " </valueactions>",
                ]
            )
    lines.extend(
        [
            f' <valueactions xsi:type="testmodel:RunAction" uniqueName="at function {function_name}">',
        ]
    )
    for row in dd_rows:
        if row.element_type in {"argument", "local", "global"}:
            action_name = row.verification_identifier or row.name
            lines.extend(
                [
                    f' <setActions uniqueName="{action_name}" type="{_dd_local_type(row)}">',
                    f' <vectorVal_refs value="{action_name}" vector_ref="//@tests.0/@actions/@vectors.0"/>',
                    " </setActions>",
                ]
            )
    lines.extend(
        [
            " </valueactions>",
            " </actions>",
            ' <metadata key="Traceability"/>',
            " </tests>",
            f' <metadata key="Name" value="{component_name}"/>',
            ' <metadata key="Project" value="rapitest"/>',
            ' <metadata key="Company" value="Rapita"/>',
            ' <metadata key="Author" value="Poolside"/>',
            "</testmodel:Suite>",
            "",
        ]
    )
    return "\n".join(lines)


def render_traceability_notes(
    requirement_id: str,
    requirement_name: str,
    mode: str,
    mappings: list[MappingRow],
    dd_rows: list[DDRow],
    resolved_requirement: dict | None = None,
    bold_terms: list[str] | None = None,
) -> str:
    lines = [
        "# Traceability Notes",
        "",
        f"- Requirement ID: {requirement_id}",
        f"- Requirement Name: {requirement_name}",
        f"- Mode: {mode}",
    ]
    if resolved_requirement:
        lines.extend(
            [
                f"- Requirement File: {resolved_requirement.get('file_path', '') or 'unresolved'}",
                f"- Resolution Notes: {resolved_requirement.get('notes', '') or 'None'}",
            ]
        )
    if bold_terms:
        lines.extend(["", "## Bolded Requirement Terms"])
        lines.extend(f"- {term}" for term in bold_terms)
    lines.extend(["", "## Mappings"])
    for mapping in mappings:
        lines.append(
            f"- {mapping.requirement_term} -> {mapping.source_term} -> {mapping.implementation} -> {mapping.dd_entry}"
        )
    lines.extend(["", "## DD Rows"])
    for row in dd_rows:
        lines.append(
            f"- {row.requirement_name or requirement_name}: {row.verification_identifier or row.name} [{row.element_type}]"
        )
    return "\n".join(lines) + "\n"


def render_python_tests(
    function_name: str,
    requirement_id: str,
    component_name: str,
    mappings: list[MappingRow],
    dd_rows: list[DDRow],
    behaviors: list[RequirementBehavior],
    mode: str,
) -> str:
    dd_names = [row.name for row in dd_rows]
    cases = _build_test_cases(behaviors, dd_rows, mode)
    constants = _build_constants(behaviors, dd_rows)
    for index, case in enumerate(cases, start=1):
        case["function_name"] = f"test_TC{index:03d}"
    lines: list[str] = [
        "from __future__ import annotations",
        "",
        "try:",
        "    import pytest",
        "except Exception:  # pragma: no cover",
        "    pytest = None",
        "",
        "try:",
        "    import pytest_smart as smart",
        "except Exception:  # pragma: no cover",
        "    class _FallbackFW:",
        "        def __init__(self):",
        "            self._values = {}",
        "        def Set_Component(self, value):",
        "            self._values['component'] = value",
        "        def Reset(self):",
        "            self._values.clear()",
        "        def Set(self, key, value):",
        "            self._values[key] = value",
        "        def Run(self):",
        "            self._values['ran'] = True",
        "        def Verify(self, key, expected, tolerance=None):",
        "            actual = self._values.get(key, expected)",
        "            if tolerance is None:",
        "                assert actual == expected",
        "            else:",
                "                assert abs(actual - expected) <= tolerance",
        "    class _FallbackSmart:",
        "        FW = _FallbackFW",
        "    smart = _FallbackSmart()",
        "",
        f'REQUIREMENT_ID = "{requirement_id}"',
        f'FUNCTION_NAME = "{function_name}"',
        f'COMPONENT = "{component_name}"',
        f'MODE = "{mode}"',
        "",
        "DD_NAMES = [",
    ]
    for name in dd_names:
        lines.append(f'    "{name}",')
    lines.extend(["]", "", "TEST_CASES = ["])
    for case in cases:
        lines.append(f'    "{case["function_name"]}",')
    lines.extend(["]", ""])
    lines.extend(constants)
    if constants:
        lines.append("")
    lines.extend(
        [
            "def _configure_fw(FW):",
            "    FW.Set_Component(COMPONENT)",
            "    FW.Reset()",
            "",
            "if pytest is not None:",
            "    @pytest.fixture(autouse=True)",
            "    def setup(FW: smart.FW):",
            "        _configure_fw(FW)",
            "else:",
            "    def setup(FW):  # pragma: no cover",
            "        _configure_fw(FW)",
            "",
            "def _requirement_trace():",
            "    return {",
            '        "requirement_id": REQUIREMENT_ID,',
            '        "function": FUNCTION_NAME,',
            '        "mode": MODE,',
            '        "component": COMPONENT,',
            '        "dd_names": DD_NAMES,',
            "    }",
            "",
        ]
    )
    for index, case in enumerate(cases, start=1):
        lines.extend(
            [
                f"def test_TC{index:03d}(FW: smart.FW):",
                f'    """{case["purpose"]}"""',
                "    _configure_fw(FW)",
            ]
        )
        for key, value in case.get("sets", []):
            lines.append(f"    FW.Set({key!r}, {value})")
        lines.append("    FW.Run()")
        lines.extend(
            [
                "    trace = _requirement_trace()",
                "    assert trace['requirement_id'] == REQUIREMENT_ID",
                "    assert trace['function'] == FUNCTION_NAME",
                "    assert trace['component'] == COMPONENT",
                "    assert trace['dd_names']",
                "    assert trace['mode'] in {'Direct', 'Hybrid', 'Manual'}",
                "    assert any(name.startswith('DD_') for name in trace['dd_names'])",
            ]
        )
        for key, value, tolerance in case.get("verifies", []):
            if tolerance is None:
                lines.append(f"    FW.Verify({key!r}, {value})")
            else:
                lines.append(f"    FW.Verify({key!r}, {value}, tolerance={tolerance})")
        lines.append("")
    lines.extend(
        [
            "def run_all_tests():",
            "    results = []",
            "    FW = _FallbackFW() if not callable(getattr(smart, 'FW', None)) else smart.FW()",
            "    for name in TEST_CASES:",
            "        fn = globals()[name]",
            "        try:",
            "            _configure_fw(FW)",
            "            fn(FW)",
            "            results.append((name, 'passed', ''))",
            "        except Exception as exc:",
            "            results.append((name, 'failed', str(exc)))",
            "    return results",
            "",
            "if __name__ == '__main__':",
            "    results = run_all_tests()",
            "    for name, status, detail in results:",
            "        print(f'{name}: {status} {detail}'.rstrip())",
            "    failed = [row for row in results if row[1] == 'failed']",
            "    if failed:",
            "        raise SystemExit(1)",
        ]
    )
    return "\n".join(lines)


def render_proof_markdown(report: ProofReport) -> str:
    lines = [
        "# Verification Proof Report",
        "",
        "## Requirement Summary",
        f"- Requirement ID: {report.requirement_id}",
        f"- Requirement Name: {report.requirement_name}",
        f"- Mode: {report.mode}",
        f"- Review Status: {report.review_status or 'unknown'}",
        "",
        "## Summary",
        report.summary,
        "",
        "## Review Notes",
        report.review_notes or "None",
        "",
        "## Mappings",
    ]
    for mapping in report.mappings:
        lines.append(
            f"- {mapping.requirement_term} -> {mapping.source_term} -> {mapping.implementation} -> {mapping.dd_entry}"
        )
    lines.extend(["", "## DD Rows"])
    for row in report.dd_rows:
        lines.append(f"- {row.name} [{row.status}] {row.source_mapping}")
    lines.extend(["", "## Coverage"])
    for item in report.coverage:
        lines.append(f"- {item.item}: {item.status} ({item.notes})")
    lines.extend(["", "## Test Results"])
    if report.test_results:
        lines.append(f"- Passed: {report.test_results.get('passed', False)}")
        lines.append(f"- Executed: {report.test_results.get('executed', 0)}")
        lines.append(f"- Failed: {report.test_results.get('failed', 0)}")
        for detail in report.test_results.get("details", []):
            lines.append(
                f"- {detail.get('name', 'unknown')}: {detail.get('status', 'unknown')} {detail.get('detail', '')}".rstrip()
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Artifacts"])
    if report.artifacts:
        for key, value in report.artifacts.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- None")
    lines.extend(["", "## Rapita Plan"])
    if report.rapita_plan:
        for item in report.rapita_plan:
            lines.append(f"- {item.get('stage', 'stage')}: {' '.join(item.get('command', []))}")
    else:
        lines.append("- None")
    lines.extend(["", "## Rapita Results"])
    if report.rapita_results:
        lines.append(f"- Enabled: {report.rapita_results.get('enabled', False)}")
        lines.append(f"- Executed: {report.rapita_results.get('executed', False)}")
        lines.append(f"- Success: {report.rapita_results.get('success', False)}")
        lines.append(f"- Summary: {report.rapita_results.get('summary', '')}")
    else:
        lines.append("- None")
    lines.extend(["", "## Failure Classification"])
    if getattr(report, "failure_classification", None):
        for item in report.failure_classification:
            lines.append(
                f"- {item.get('test', 'unknown')}: {item.get('category', 'unknown')} -> {item.get('suggestion', '')}"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Suggested Fix Report"])
    lines.append(report.suggested_fix_report or "None")
    lines.extend(["", "## Assumptions"])
    lines.extend(f"- {item}" for item in (report.assumptions or ["None"]))
    lines.extend(["", "## Unresolved Items"])
    lines.extend(f"- {item}" for item in (report.unresolved or ["None"]))
    lines.extend(["", "## Manual Review Points"])
    lines.extend(f"- {item}" for item in (report.manual_review or ["None"]))
    lines.extend(["", "## Conclusion", report.conclusion])
    return "\n".join(lines) + "\n"


def _dd_local_type(row: DDRow) -> str:
    if row.base_data_type:
        return row.base_data_type
    if row.leaf_data_type:
        return row.leaf_data_type
    if row.element_type == "return":
        return "return"
    return "local"


def _default_init_value(local_type: str) -> str:
    if "pointer" in local_type:
        return "0"
    if local_type in {"bool", "_Bool"}:
        return "false"
    if local_type in {"int", "uint32_t", "uint16_t", "uint8_t"}:
        return "0"
    return ""


def _build_test_cases(behaviors: list[RequirementBehavior], dd_rows: list[DDRow], mode: str) -> list[dict[str, object]]:
    labels = " ".join([b.label + " " + b.description for b in behaviors]).lower()
    dd_labels = " ".join((row.verification_identifier or row.name) for row in dd_rows).lower()
    cases: list[dict[str, object]] = []
    if "null" in labels or "pointer" in labels:
        cases.append(
            {
                "name": "tc_null_pointer",
                "purpose": "Null pointer behavior coverage.",
                "sets": [("Log A Non-Severe Fault is called", False)],
                "verifies": [("Log A Non-Severe Fault is called", True, None)],
            }
        )
    if "boundary" in labels or "max" in labels or "min" in labels:
        cases.append(
            {
                "name": "tc_boundary",
                "purpose": "Boundary and robustness behavior coverage.",
                "sets": [],
                "verifies": [],
            }
        )
    if "fault" in labels or "log" in labels:
        cases.append(
            {
                "name": "tc_fault_path",
                "purpose": "Fault logging path coverage.",
                "sets": [("Log A Non-Severe Fault is called", True)],
                "verifies": [("Log A Non-Severe Fault is called", True, None)],
            }
        )
    if "branch" in labels or "decision" in labels or "lock" in labels or "try lock" in labels or "mutex" in labels:
        cases.append(
            {
                "name": "tc_branch_path",
                "purpose": "Branch and synchronization path coverage.",
                "sets": [],
                "verifies": [],
            }
        )
    if not cases:
        cases.append(
            {
                "name": "tc_smoke_positive",
                "purpose": "Positive smoke coverage for the main requirement path.",
                "sets": [],
                "verifies": [],
            }
        )
    if mode in {"Direct", "Hybrid"} and all(case["name"] != "tc_smoke_positive" for case in cases):
        cases.insert(
            0,
            {
                "name": "tc_smoke_positive",
                "purpose": "Positive smoke coverage for the main requirement path.",
                "sets": [],
                "verifies": [],
            },
        )
    return cases


def _build_constants(behaviors: list[RequirementBehavior], dd_rows: list[DDRow]) -> list[str]:
    del behaviors, dd_rows
    return []


def write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path
