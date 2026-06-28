from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Optional

from scripts.workspace_utils import detect_workspace_root

from llt_eval_assess import RequirementAssessMixin
from llt_eval_data import RequirementDataMixin
from llt_eval_extract import RequirementExtractMixin
from llt_eval_lookup import RequirementLookupMixin
from llt_eval_methods import RequirementMethodMixin
from llt_eval_report import RequirementReportMixin
from llt_eval_rbtca import RequirementRBTCAMixin
from llt_eval_testgen import RequirementTestGenMixin


class RequirementEvaluator(
    RequirementDataMixin,
    RequirementExtractMixin,
    RequirementLookupMixin,
    RequirementAssessMixin,
    RequirementMethodMixin,
    RequirementReportMixin,
    RequirementRBTCAMixin,
    RequirementTestGenMixin,
):
    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = detect_workspace_root(workspace_root)
        self.requirement_dirs = [self.workspace_root / "requirements" / "LLR", self.workspace_root / "requirements" / "llr", self.workspace_root / "LLR"]
        self.data_dict_dirs = [self.workspace_root / "requirements" / "data_dictionary", self.workspace_root / "verification" / "test-procedures" / "procedure-data"]
        self.procedure_data_dirs = [self.workspace_root / "verification" / "test-procedures" / "procedure-data"]
        self.source_dirs = [self.workspace_root / "software" / "source", self.workspace_root / "source", self.workspace_root / "src"]
        self.test_cases_dirs = [self.workspace_root / "verification" / "test-cases" / "low_level", self.workspace_root / "verification" / "test-cases"]
        self.rbtca_dirs = [self.workspace_root / "records" / "rbtca" / "low_level", self.workspace_root / "records" / "rbtca"]
        self.procedure_vectors_dirs = [self.workspace_root / "verification" / "test-procedures" / "procedure-vectors"]
        self.data_dict_terms = {}
        self.uut_dict_terms = {}
        self.extracted_terms = {}
        self.source_terms = {}
        self.source_constants = []
        self.source_constraints = []
        self.procedure_data_terms = {}


def verify_requirement(arg: str, step2_mode: bool = False, generate_rbtca: bool = False, generate_test: bool = False) -> None:
    evaluator = RequirementEvaluator()
    result = evaluator.evaluate(arg, allow_source_reading=True)
    if step2_mode:
        print(evaluator.generate_step2_output(result))
        return
    if generate_rbtca:
        print(json.dumps(evaluator.generate_rbtca_yaml(result, "generated")[0], indent=2))
        return
    if generate_test:
        print(evaluator.generate_test_case_file(result, "generated", arg))
        return
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("arg", nargs="?", default="")
    parser.add_argument("--step2", action="store_true")
    parser.add_argument("--generate-rbtca", action="store_true")
    parser.add_argument("--generate-test", action="store_true")
    args = parser.parse_args()
    verify_requirement(args.arg, step2_mode=args.step2, generate_rbtca=args.generate_rbtca, generate_test=args.generate_test)
