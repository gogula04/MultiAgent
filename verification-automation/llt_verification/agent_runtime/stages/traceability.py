from __future__ import annotations

import yaml_compat as yaml
import re
from pathlib import Path
from typing import Any, Dict, List, Set

from ..core import BaseStageAgent
from ..validators import validate_contract


class TraceabilityAgent(BaseStageAgent):
    name = "Traceability Agent"
    stage = "07_traceability"

    def _collect_tc_ids(self, value: Any, ids: Set[str]) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                self._collect_tc_ids(key, ids)
                self._collect_tc_ids(item, ids)
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                self._collect_tc_ids(item, ids)
            return
        text = str(value)
        for match in re.findall(r"TC(\d{3})", text):
            ids.add(match)

    def _rbtca_case_ids(self, rbtca_path: Path) -> Set[str]:
        ids: Set[str] = set()
        try:
            parsed = yaml.safe_load(rbtca_path.read_text())
        except Exception:
            parsed = None
        if parsed is not None:
            self._collect_tc_ids(parsed, ids)
        if not ids:
            self._collect_tc_ids(rbtca_path.read_text(errors="ignore"), ids)
        return ids

    def _python_case_ids(self, test_path: Path) -> Set[str]:
        ids: Set[str] = set()
        try:
            self._collect_tc_ids(test_path.read_text(errors="ignore"), ids)
        except Exception:
            return ids
        return ids

    def run(self, result: Dict[str, object], decision: Dict[str, object], artifacts: Dict[str, object]) -> Dict[str, object]:
        issues: List[str] = []
        rbtca_path = Path(artifacts["rbtca_file"])
        test_path = Path(artifacts["test_file"])
        rbtca_ids: Set[str] = set()
        test_ids: Set[str] = set()
        if not rbtca_path.exists():
            issues.append("RBTCA file missing")
        else:
            rbtca_ids = self._rbtca_case_ids(rbtca_path)
        if not test_path.exists():
            issues.append("Python test file missing")
        else:
            test_ids = self._python_case_ids(test_path)
        if decision["selected_method"] == "hybrid" and "rvstest_file" not in artifacts:
            issues.append(".rvstest file missing for Hybrid path")
        if decision["selected_method"] == "hybrid" and "rvstest_file" in artifacts:
            rvstest_path = Path(artifacts["rvstest_file"])
            if not rvstest_path.exists():
                issues.append(".rvstest file missing for Hybrid path")
        if not test_ids:
            issues.append("No test case functions found")
        if rbtca_ids and test_ids and rbtca_ids != test_ids:
            missing_from_tests = sorted(rbtca_ids - test_ids)
            missing_from_rbtca = sorted(test_ids - rbtca_ids)
            if missing_from_tests:
                issues.append(f"Missing Python tests for RBTCA IDs: {', '.join(missing_from_tests)}")
            if missing_from_rbtca:
                issues.append(f"Missing RBTCA IDs for Python tests: {', '.join(missing_from_rbtca)}")
        payload = {"requirement_id": result["requirement_id"], "passed": not issues, "issues": issues, "status": "passed" if not issues else "failed"}
        validate_contract("traceability_result", payload)
        self.emit(payload["status"], payload, next_agent="execution" if not issues else "proof")
        return payload
