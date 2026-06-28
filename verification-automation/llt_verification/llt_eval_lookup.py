from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple


class RequirementLookupMixin:
    def _normalize_evidence_key(self, text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", (text or "").lower())

    def _parse_source_evidence_literal(self, raw_value: object) -> object:
        if raw_value is None:
            return None
        if isinstance(raw_value, (bool, int, float)):
            return raw_value
        text = str(raw_value).strip()
        if not text:
            return None
        lowered = text.lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
        if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
            return text[1:-1]
        try:
            return int(text, 0)
        except Exception:
            pass
        try:
            return float(text)
        except Exception:
            return None

    def get_source_evidence_for_term(self, term: str) -> Dict[str, List[Dict]]:
        term_key = self._normalize_evidence_key(term)
        term_tokens = {tok for tok in re.findall(r"[a-z0-9]+", term.lower()) if tok}
        constants = []
        constraints = []
        for info in getattr(self, "source_constants", []):
            name = str(info.get("name", ""))
            name_key = self._normalize_evidence_key(name)
            name_tokens = {tok for tok in re.findall(r"[a-z0-9]+", name.lower()) if tok}
            if term_key and (term_key == name_key or term_key in name_key or name_key in term_key or term_tokens.intersection(name_tokens)):
                constants.append(info)
        for info in getattr(self, "source_constraints", []):
            expression = str(info.get("expression", ""))
            expr_key = self._normalize_evidence_key(expression)
            if term_key and (term_key in expr_key or expr_key in term_key or term_tokens.intersection({tok for tok in re.findall(r"[a-z0-9]+", expression.lower()) if tok})):
                constraints.append(info)
        return {"constants": constants, "constraints": constraints}

    def get_source_value_candidates(self, term: str) -> List[object]:
        evidence = self.get_source_evidence_for_term(term)
        candidates: List[object] = []
        for item in evidence.get("constants", []):
            value = self._parse_source_evidence_literal(item.get("value"))
            if value is not None and value not in candidates:
                candidates.append(value)
        for item in evidence.get("constraints", []):
            rhs = item.get("rhs")
            if rhs is not None:
                value = self._parse_source_evidence_literal(rhs)
                if value is not None and value not in candidates:
                    candidates.append(value)
        return candidates

    def check_terms_in_dictionaries(self, terms: List[str]) -> Tuple[List[str], List[str]]:
        found, not_found = [], []
        for term in terms:
            lower = term.lower()
            (found if any(lower in t or t in lower for t in self.data_dict_terms.keys()) else not_found).append(term)
        return found, not_found

    def get_term_type(self, term: str) -> Optional[str]:
        lower = term.lower()
        for dict_term, info in self.data_dict_terms.items():
            if lower in dict_term or dict_term in lower:
                return info.get("type", "unknown")
        for header_term, info in self.source_terms.items():
            if lower in header_term or header_term in lower:
                return info.get("type", "header file")
        return None

    def get_term_info(self, term: str) -> Optional[Dict]:
        lower = term.lower()
        for dict_term, info in self.data_dict_terms.items():
            if lower in dict_term or dict_term in lower:
                return info
        for uut_term, info in self.uut_dict_terms.items():
            if lower in uut_term or uut_term in lower:
                return info
        for extracted_term, info in getattr(self, "extracted_terms", {}).items():
            if lower in extracted_term or extracted_term in lower:
                return info
        for header_term, info in self.source_terms.items():
            if lower in header_term or header_term in lower:
                return info
        return None

    def check_terms_in_headers(self, terms: List[str]) -> Tuple[List[str], List[str]]:
        found, not_found = [], []
        for term in terms:
            lower = term.lower()
            (found if any(lower in t or t in lower for t in self.source_terms.keys()) else not_found).append(term)
        return found, not_found

    def _find_uut_dictionary_matches(self, terms: List[str]) -> Dict[str, List[str]]:
        found, not_found = [], []
        for term in terms:
            lower = term.lower()
            (found if any(lower in t or t in lower for t in self.uut_dict_terms.keys()) else not_found).append(term)
        return {"found": found, "not_found": not_found}

    def _lookup_uut_entry(self, component_name: str) -> Optional[Dict]:
        if not component_name:
            return None
        lower = component_name.lower()
        for uut_name, info in self.uut_dict_terms.items():
            if lower in uut_name or uut_name in lower:
                return info
        return None

    def _sample_values_for_term(self, term: str, term_info: Optional[Dict]) -> Dict[str, object]:
        t = str((term_info or {}).get("type", "")).lower()
        enum_values = (term_info or {}).get("enum_values") or (term_info or {}).get("valid_values") or []
        if any(x in t for x in {"enum", "enumeration"}) or enum_values:
            values = list(enum_values) if isinstance(enum_values, list) else [enum_values]
            values = [v for v in values if v is not None]
            if not values:
                values = ["VALID_A", "VALID_B"]
            return {"nominal": values[0], "valid_values": values, "invalid": "__INVALID__", "minimum": values[0], "maximum": values[-1]}
        if any(x in t for x in {"bool", "boolean"}):
            return {"true": True, "false": False, "nominal": True}
        if any(x in t for x in {"string", "char"}):
            return {"nominal": "VALID", "empty": "", "invalid": "@@@"}
        if any(x in t for x in {"float", "double", "real", "int", "integer", "int32", "int64", "uint32", "uint64"}):
            try:
                mn = float(term_info.get("min")) if term_info and term_info.get("min") is not None else 0.0
            except Exception:
                mn = 0.0
            try:
                mx = float(term_info.get("max")) if term_info and term_info.get("max") is not None else 1.0
            except Exception:
                mx = 1.0
            if mx <= mn:
                mx = mn + 1.0
            return {"minimum": mn, "maximum": mx, "below_min": mn - 1.0, "above_max": mx + 1.0, "zero": 0.0, "nominal": mn}
        return {"nominal": 1, "minimum": 0, "maximum": 1, "below_min": -1, "above_max": 2, "zero": 0}

    def _placeholder_expected_literal(self, term_info: Optional[Dict], case_title: str = "") -> str:
        t = str((term_info or {}).get("type", "")).lower()
        lower = case_title.lower()
        if "bool" in t or "boolean" in t:
            return "False" if "false" in lower else "True"
        if "string" in t or "char" in t:
            return '""'
        return "0.0"
