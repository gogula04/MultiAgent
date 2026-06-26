#!/usr/bin/env python3
"""Importable entrypoint for the LLT verification workflow."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_SOURCE = Path(__file__).with_name("llt-verification.py")
_SPEC = spec_from_file_location("llt_verification_impl", _SOURCE)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Unable to load verification implementation from {_SOURCE}")

_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

RequirementEvaluator = _MODULE.RequirementEvaluator
verify_requirement = _MODULE.verify_requirement
main = _MODULE.main


if __name__ == "__main__":
    main()
