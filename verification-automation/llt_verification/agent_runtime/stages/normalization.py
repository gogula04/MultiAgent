from __future__ import annotations

from typing import Dict

from ..core import BaseStageAgent, normalize_term
from ..validators import validate_contract


class TermNormalizationAgent(BaseStageAgent):
    name = "Term Normalization Agent"
    stage = "03_term_normalization"

    def run(self, requirement_package: Dict[str, object], evidence_package: Dict[str, object]) -> Dict[str, object]:
        terms = list(dict.fromkeys(requirement_package.get("bold_terms", []) + requirement_package.get("inputs", []) + requirement_package.get("outputs", [])))
        contract_aliases = requirement_package.get("extraction_contract", {}).get("aliases", {}) if isinstance(requirement_package.get("extraction_contract", {}), dict) else {}
        aliases = {}
        for term in terms:
            alias_meta = contract_aliases.get(term, {}) if isinstance(contract_aliases, dict) else {}
            variants = list(dict.fromkeys([term] + list(alias_meta.get("variants", [])) + [normalize_term(term), f"dd_{normalize_term(term)}"]))
            aliases[term] = {
                "normalized": normalize_term(term),
                "dd_name": f"dd_{normalize_term(term)}",
                "variants": variants,
            }
        payload = {"requirement_id": requirement_package["requirement_id"], "normalized_terms": terms, "aliases": aliases, "status": "completed"}
        validate_contract("normalized_terms_package", payload)
        self.emit("completed", payload, evidence={"evidence_package": evidence_package}, next_agent="poolside_analysis")
        return payload
