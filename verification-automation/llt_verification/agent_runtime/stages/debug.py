from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from ..core import BaseStageAgent
from ..validators import validate_contract


class DebugAgent(BaseStageAgent):
    name = "Debug Agent"
    stage = "09_debug"

    def _patch_placeholders(self, test_file: Path, result: Dict[str, object]) -> List[str]:
        content = test_file.read_text(errors="ignore")
        changed: List[str] = []
        for term in re.findall(r'FW\.Verify\("([^"]+)"', content):
            if "# Placeholder" not in content and "TODO" not in content:
                continue
            term_info = self.evaluator.get_term_info(term)
            replacement = "False" if "bool" in str((term_info or {}).get("type", "")).lower() else "0.0"
            replacement_line = f'FW.Verify("{term}", {replacement}) # Placeholder - adjust based on requirement'
            content = re.sub(rf'FW\.Verify\("{re.escape(term)}",\s*0\.0\)\s*# Placeholder - adjust based on requirement', replacement_line, content)
            changed.append(term)
        if changed:
            test_file.write_text(content)
        return changed

    def run(self, artifacts: Dict[str, object], execution_result: Dict[str, object], continue_on_failure: bool = False) -> Dict[str, object]:
        self.evaluator.load_source_terms()
        source_constants = getattr(self.evaluator, "source_constants", [])
        source_constraints = getattr(self.evaluator, "source_constraints", [])
        if execution_result.get("status") == "passed" or not continue_on_failure:
            payload = {"requirement_id": artifacts["requirement_id"], "status": "skipped" if execution_result.get("status") == "passed" else "not_run", "attempts": 0, "changes": [], "execution_result": execution_result, "source_constants": source_constants, "source_constraints": source_constraints}
            validate_contract("debug_result", payload)
            self.emit(payload["status"], payload, next_agent="review")
            return payload
        test_file = Path(artifacts["test_file"])
        changes = self._patch_placeholders(test_file, artifacts)
        rerun = self.runtime.run_pytest(test_file, artifacts["requirement_id"])
        payload = {"requirement_id": artifacts["requirement_id"], "status": rerun["status"], "attempts": 1 if changes else 0, "changes": changes, "execution_result": rerun, "source_constants": source_constants, "source_constraints": source_constraints}
        validate_contract("debug_result", payload)
        self.emit(payload["status"], payload, next_agent="review")
        return payload
