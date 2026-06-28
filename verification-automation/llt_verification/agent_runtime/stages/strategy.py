from __future__ import annotations

from typing import Dict

from ..core import BaseStageAgent
from ..validators import validate_contract


class StrategyAgent(BaseStageAgent):
    name = "Strategy Agent"
    stage = "05_strategy"

    def _branch_note(self, decision: Dict[str, object]) -> str:
        selected_method = str(decision.get("selected_method") or "unknown").strip()
        reason = " ".join(str(decision.get("reason") or "").split())
        if reason:
            return f"{selected_method.title()} selected: {reason}"
        return f"{selected_method.title()} selected."

    def run(self, requirement_package: Dict[str, object], evidence_package: Dict[str, object], analysis_package: Dict[str, object]) -> Dict[str, object]:
        result = dict(evidence_package)
        result.update({"component_name": requirement_package.get("component_name"), "requirement_id": requirement_package["requirement_id"]})
        decision = self.evaluator.make_method_decision(result, requirement_package.get("component_name"))
        branch_note = self._branch_note(decision)
        payload = {
            "requirement_id": requirement_package["requirement_id"],
            "selected_method": decision.get("selected_method", "blocked"),
            "reason": decision.get("reason", ""),
            "evidence": decision.get("evidence", {}),
            "evidence_citations": evidence_package.get("retrieval_summary", {}),
            "proof_table": decision.get("proof_table", []),
            "branch_note": branch_note,
            "reuse_candidates": analysis_package.get("reuse_candidates", []),
            "analysis_hint": analysis_package,
            "status": "completed",
        }
        validate_contract("strategy_decision", payload)
        self.emit("completed", payload, evidence=decision, next_agent=payload["selected_method"])
        return payload
