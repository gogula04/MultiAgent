from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from ..core import BaseStageAgent
from ..validators import validate_contract


class DebugAgent(BaseStageAgent):
    name = "Debug Agent"
    stage = "09_debug"

    def _evidence_literal_for_term(self, term: str):
        if not hasattr(self.evaluator, "get_source_value_candidates"):
            return None
        candidates = self.evaluator.get_source_value_candidates(term)
        if not candidates:
            return None
        return repr(candidates[0])

    def _patch_placeholders(self, test_file: Path) -> List[str]:
        content = test_file.read_text(errors="ignore")
        lines = content.splitlines()
        changed: List[str] = []
        for idx, line in enumerate(lines):
            match = re.search(r'FW\.Verify\("([^"]+)",\s*([^)#]+)\)\s*(#.*)?$', line)
            if not match:
                continue
            term = match.group(1)
            current_literal = match.group(2).strip()
            comment = (match.group(3) or "").lower()
            placeholder_like = "placeholder" in comment or current_literal in {"0.0", "0", "False", "True", '""', "''"}
            if not placeholder_like:
                continue
            replacement = self._evidence_literal_for_term(term)
            if replacement is None or replacement == current_literal:
                continue
            start, end = match.span()
            lines[idx] = line[:start] + f'FW.Verify("{term}", {replacement})' + line[end:]
            changed.append(term)
        if changed:
            test_file.write_text("\n".join(lines) + ("\n" if content.endswith("\n") else ""))
        return changed

    def run(self, artifacts: Dict[str, object], execution_result: Dict[str, object], continue_on_failure: bool = False) -> Dict[str, object]:
        source_constants = []
        source_constraints = []
        if self.policy.implementation_access_allowed():
            self.evaluator.load_source_terms()
            source_constants = getattr(self.evaluator, "source_constants", [])
            source_constraints = getattr(self.evaluator, "source_constraints", [])
        else:
            self.state.log("Debug stage skipped implementation/source reads due to policy")
        if execution_result.get("status") == "passed" or not continue_on_failure:
            payload = {"requirement_id": artifacts["requirement_id"], "status": "skipped" if execution_result.get("status") == "passed" else "not_run", "attempts": 0, "changes": [], "execution_result": execution_result, "blocked_reason": None, "evidence_backed": False, "source_constants": source_constants, "source_constraints": source_constraints}
            validate_contract("debug_result", payload)
            self.emit(payload["status"], payload, next_agent="review")
            return payload
        test_file = Path(artifacts["test_file"])
        changes = self._patch_placeholders(test_file)
        if not changes:
            payload = {
                "requirement_id": artifacts["requirement_id"],
                "status": "blocked",
                "attempts": 0,
                "changes": [],
                "blocked_reason": "No evidence-backed placeholder repair was available",
                "evidence_backed": False,
                "execution_result": execution_result,
                "source_constants": source_constants,
                "source_constraints": source_constraints,
            }
            validate_contract("debug_result", payload)
            self.emit("blocked", payload, next_agent="review")
            return payload
        rerun = self.runtime.run_pytest(test_file, artifacts["requirement_id"])
        payload = {
            "requirement_id": artifacts["requirement_id"],
            "status": rerun["status"],
            "attempts": 1,
            "changes": changes,
            "blocked_reason": None if rerun["status"] == "passed" else (rerun.get("stderr") or rerun.get("stdout") or "Evidence-backed repair still failed"),
            "evidence_backed": True,
            "initial_execution_result": execution_result,
            "execution_result": rerun,
            "source_constants": source_constants,
            "source_constraints": source_constraints,
        }
        validate_contract("debug_result", payload)
        self.emit(payload["status"], payload, next_agent="review")
        return payload
