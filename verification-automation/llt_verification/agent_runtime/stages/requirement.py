from __future__ import annotations

import re
from typing import Dict

from ..core import BaseStageAgent
from ..validators import validate_contract


class RequirementAgent(BaseStageAgent):
    name = "Requirement Agent"
    stage = "01_requirement"

    def run(self, prompt: str) -> Dict[str, object]:
        req_id_match = re.search(r"FAF-LLR-\d+", prompt)
        requirement_id = req_id_match.group(0) if req_id_match else self.state.requirement_id
        requirement_text = prompt
        requirement_file = None
        if req_id_match:
            located_text, located_file = self.evaluator.find_requirement_by_id(requirement_id)
            if located_text:
                requirement_text = located_text
                requirement_file = str(located_file) if located_file else None
        evaluation = self.evaluator.evaluate(requirement_text, allow_source_reading=False, poolside_client=self.poolside)
        payload = {
            "requirement_id": requirement_id,
            "requirement_text": requirement_text,
            "requirement_file": requirement_file,
            "classification": evaluation["classification"],
            "inputs": evaluation["inputs"],
            "outputs": evaluation["outputs"],
            "bold_terms": evaluation["bold_terms"],
            "types_and_ranges": evaluation["types_and_ranges"],
            "expressions": evaluation["expressions"],
            "legacy_prompt_used": evaluation.get("legacy_prompt_used", []),
            "component_name": self.evaluator.extract_component_name(requirement_text),
            "status": "completed",
        }
        validate_contract("requirement_package", payload)
        self.emit("completed", payload, next_agent="repo_evidence")
        return payload
