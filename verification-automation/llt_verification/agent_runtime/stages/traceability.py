from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from ..core import BaseStageAgent
from ..validators import validate_contract


class TraceabilityAgent(BaseStageAgent):
    name = "Traceability Agent"
    stage = "07_traceability"

    def run(self, result: Dict[str, object], decision: Dict[str, object], artifacts: Dict[str, object]) -> Dict[str, object]:
        issues: List[str] = []
        rbtca_path = Path(artifacts["rbtca_file"])
        test_path = Path(artifacts["test_file"])
        if not rbtca_path.exists():
            issues.append("RBTCA file missing")
        if not test_path.exists():
            issues.append("Python test file missing")
        if decision["selected_method"] == "hybrid" and "rvstest_file" not in artifacts:
            issues.append(".rvstest file missing for Hybrid path")
        if not re.findall(r"def\s+test_TC(\d{3})", test_path.read_text(errors="ignore") if test_path.exists() else ""):
            issues.append("No test case functions found")
        payload = {"requirement_id": result["requirement_id"], "passed": not issues, "issues": issues, "status": "passed" if not issues else "failed"}
        validate_contract("traceability_result", payload)
        self.emit(payload["status"], payload, next_agent="execution" if not issues else "proof")
        return payload
