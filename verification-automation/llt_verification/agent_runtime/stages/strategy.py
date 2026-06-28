from __future__ import annotations

from typing import Dict

from ..core import BaseStageAgent
from ..validators import validate_contract


class StrategyAgent(BaseStageAgent):
    name = "Strategy Agent"
    stage = "05_strategy"

    def run(self, requirement_package: Dict[str, object], evidence_package: Dict[str, object], analysis_package: Dict[str, object]) -> Dict[str, object]:
        result = dict(evidence_package)
        result.update({"component_name": requirement_package.get("component_name"), "requirement_id": requirement_package["requirement_id"]})
        decision = self.evaluator.make_method_decision(result, requirement_package.get("component_name"))
        payload = {
            "requirement_id": requirement_package["requirement_id"],
            "selected_method": decision.get("selected_method", "blocked"),
            "reason": decision.get("reason", ""),
            "evidence": decision.get("evidence", {}),
            "analysis_hint": analysis_package,
            "status": "completed",
        }
        validate_contract("strategy_decision", payload)
        self.emit("completed", payload, evidence=decision, next_agent=payload["selected_method"])
        return payload
