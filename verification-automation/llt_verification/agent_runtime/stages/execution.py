from __future__ import annotations

from pathlib import Path
from typing import Dict
import shutil
import subprocess

from ..core import BaseStageAgent
from ..validators import validate_contract


class ExecutionAgent(BaseStageAgent):
    name = "Execution Agent"
    stage = "08_execution"

    def run(self, artifacts: Dict[str, object], decision: Dict[str, object], dry_run: bool = False) -> Dict[str, object]:
        test_file = Path(artifacts["test_file"])
        if dry_run:
            payload = {"requirement_id": artifacts["requirement_id"], "status": "dry_run", "command": f"pytest {test_file}", "exit_code": None, "stdout": "", "stderr": ""}
            validate_contract("execution_result", payload)
            self.emit("dry_run", payload, next_agent="review")
            return payload
        command = ["pytest", str(test_file), "-v", "--tb=short"]
        if decision["selected_method"] == "hybrid" and shutil.which("rvs"):
            command = ["rvs", str(artifacts.get("rvstest_file", "")), str(test_file)]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            payload = {"requirement_id": artifacts["requirement_id"], "status": "timeout", "command": " ".join(command), "exit_code": None, "stdout": "", "stderr": "Execution timed out"}
            validate_contract("execution_result", payload)
            self.emit("timeout", payload, next_agent="debug")
            return payload
        except Exception as exc:
            payload = {"requirement_id": artifacts["requirement_id"], "status": "error", "command": " ".join(command), "exit_code": None, "stdout": "", "stderr": str(exc)}
            validate_contract("execution_result", payload)
            self.emit("error", payload, next_agent="debug")
            return payload
        status = "passed" if completed.returncode == 0 else "failed"
        payload = {"requirement_id": artifacts["requirement_id"], "status": status, "command": " ".join(command), "exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}
        validate_contract("execution_result", payload)
        self.emit(status, payload, next_agent="debug" if status != "passed" else "review")
        return payload
