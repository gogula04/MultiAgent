from __future__ import annotations

from typing import Dict

from ..core import BaseStageAgent
from ..validators import validate_contract


class ReviewerAgent(BaseStageAgent):
    name = "Reviewer Agent"
    stage = "10_review"

    def run(
        self,
        requirement_package: Dict[str, object],
        evidence_package: Dict[str, object],
        artifacts: Dict[str, object],
        execution_result: Dict[str, object],
        debug_result: Dict[str, object],
        decision: Dict[str, object],
    ) -> Dict[str, object]:
        self.evaluator.load_source_terms()
        source_constants = getattr(self.evaluator, "source_constants", [])
        source_constraints = getattr(self.evaluator, "source_constraints", [])
        poolside_response = self.poolside.complete(
            "review",
            {
                "requirement": requirement_package,
                "evidence": evidence_package,
                "artifacts": artifacts,
                "execution_result": execution_result,
                "debug_result": debug_result,
                "decision": decision,
                "source_constants": source_constants,
                "source_constraints": source_constraints,
            },
        )
        parsed = poolside_response.get("parsed_content") if isinstance(poolside_response.get("parsed_content"), dict) else {}
        issues = []
        if decision.get("selected_method") == "blocked":
            issues.append("strategy chose blocked")
        if execution_result.get("status") not in {"passed", "dry_run"}:
            issues.append("execution did not pass")
        if debug_result.get("status") not in {"passed", "skipped", "not_run", "dry_run"}:
            issues.append("debug did not finish cleanly")
        status = "approved" if not issues else "rejected"
        payload = {
            "requirement_id": requirement_package["requirement_id"],
            "status": status,
            "summary": parsed.get("summary") or ("Verification bundle is consistent." if status == "approved" else "Verification bundle needs fixes."),
            "issues": parsed.get("issues", issues),
            "recommendations": parsed.get("recommendations", []),
            "source_constants": source_constants,
            "source_constraints": source_constraints,
            "poolside_response": poolside_response,
        }
        validate_contract("review_result", payload)
        self.emit(status, payload, evidence=poolside_response, next_agent="proof")
        return payload
