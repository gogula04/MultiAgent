"""Execute generated verification artifacts."""

from __future__ import annotations

import importlib.util
import io
import py_compile
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .state import VerificationState


@dataclass(slots=True)
class ExecutionResult:
    passed: bool
    executed: int
    failed: int
    details: list[dict[str, str]]
    stdout: str = ""
    stderr: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def execute_generated_tests(state: VerificationState, output_dir: Path) -> VerificationState:
    test_file = output_dir / "test_requirement_generated.py"
    if not test_file.exists():
        state["test_results"] = ExecutionResult(False, 0, 1, [{"name": "generated_tests", "status": "missing", "detail": "Generated Python test file not found."}]).to_dict()
        state.setdefault("logs", []).append("Generated Python test file missing; execution skipped.")
        return state

    try:
        py_compile.compile(str(test_file), doraise=True)
    except Exception as exc:
        state["test_results"] = ExecutionResult(False, 0, 1, [{"name": "py_compile", "status": "failed", "detail": str(exc)}]).to_dict()
        state.setdefault("logs", []).append(f"Compilation failed for generated tests: {exc}")
        return state

    buffer_out = io.StringIO()
    buffer_err = io.StringIO()
    details: list[dict[str, str]] = []
    executed = 0
    failed = 0
    try:
        spec = importlib.util.spec_from_file_location("generated_tests", test_file)
        if spec is None or spec.loader is None:
            raise RuntimeError("Could not load generated test module.")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if hasattr(module, "run_all_tests"):
            with redirect_stdout(buffer_out), redirect_stderr(buffer_err):
                results = module.run_all_tests()
            for name, status, detail in results:
                executed += 1
                if status == "failed":
                    failed += 1
                details.append({"name": name, "status": status, "detail": detail})
        else:
            for name in sorted(n for n in dir(module) if n.startswith("test_")):
                fn = getattr(module, name)
                if callable(fn):
                    executed += 1
                    try:
                        with redirect_stdout(buffer_out), redirect_stderr(buffer_err):
                            fn()
                        details.append({"name": name, "status": "passed", "detail": ""})
                    except Exception as exc:
                        failed += 1
                        details.append({"name": name, "status": "failed", "detail": str(exc)})
    except Exception as exc:
        failed = 1
        details.append({"name": "generated_tests", "status": "failed", "detail": str(exc)})

    result = ExecutionResult(
        passed=failed == 0,
        executed=executed,
        failed=failed,
        details=details,
        stdout=buffer_out.getvalue(),
        stderr=buffer_err.getvalue(),
    )
    state["test_results"] = result.to_dict()
    state["status"] = "verified" if result.passed else "execution_failed"
    state.setdefault("logs", []).append(
        f"Executed {executed} generated test(s): {executed - failed} passed, {failed} failed."
    )
    return state
