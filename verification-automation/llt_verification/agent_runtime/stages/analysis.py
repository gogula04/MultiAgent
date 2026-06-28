from __future__ import annotations

from typing import Dict

from ..core import BaseStageAgent
from ..validators import validate_contract


class PoolsideAnalysisAgent(BaseStageAgent):
    name = "Poolside Analysis Agent"
    stage = "04_poolside_analysis"

    def run(self, requirement_package: Dict[str, object], evidence_package: Dict[str, object], normalization_package: Dict[str, object]) -> Dict[str, object]:
        payload = {
            "requirement_id": requirement_package["requirement_id"],
            "requirement_text": requirement_package["requirement_text"],
            "classification": requirement_package["classification"],
            "inputs": requirement_package["inputs"],
            "outputs": requirement_package["outputs"],
            "evidence": evidence_package,
            "normalized_terms": normalization_package,
        }
        poolside_response = self.poolside.complete("analysis", payload)
        parsed = poolside_response.get("parsed_content")
        if not isinstance(parsed, dict):
            parsed = {}
        analysis = {
            "requirement_id": requirement_package["requirement_id"],
            "summary": parsed.get("summary") or poolside_response.get("content") or "Poolside analysis completed.",
            "key_signals": parsed.get("key_signals", normalization_package.get("normalized_terms", [])),
            "likely_method": parsed.get("likely_method", "unknown"),
            "risks": parsed.get("risks", []),
            "recommendations": parsed.get("recommendations", []),
            "poolside_response": poolside_response,
            "status": "completed",
        }
        validate_contract("analysis_package", analysis)
        self.emit("completed", analysis, evidence=poolside_response, next_agent="strategy")
        return analysis
