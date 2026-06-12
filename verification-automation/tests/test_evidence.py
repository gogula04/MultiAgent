from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from verification_automation.artifacts import render_python_tests
from verification_automation.models import DDRow, RequirementBehavior, RequirementInput
from verification_automation.orchestrator import VerificationOrchestrator
from verification_automation.rag import build_evidence_bundle
from verification_automation.repo_scan import scan_repository


QUEUE_REQUIREMENT = """### Name
Push Operation - Mutex Lock

### Item ID
FAF-LLR-1323

### Description
The **Push Element operation** utility shall use **Mutex Lock** when **Use Non Blocking Lock** input is false and return **No Error** from **Mutex Lock** utility with **Queue: Mutex** as an input.
"""

QUEUE_SOURCE = """UtlQueueStatus UtlQueuePush(UtlQueue *queue, const void *element, bool useNonBlockingLock)
{
    if (useNonBlockingLock == true)
    {
        if (MutexTryLock(queue->mutex) == NoError)
        {
            queue->mutexCounter = 0U;
        }
    }
    else
    {
        if (MutexLock(queue->mutex) == NoError)
        {
            queue->mutexCounter = 0U;
        }
    }
    return UTILQUEUE_SUCCESS;
}
"""


class EvidenceDrivenWorkflowTests(unittest.TestCase):
    def _create_queue_repo(self, root: Path) -> None:
        (root / "requirements" / "HLR").mkdir(parents=True)
        (root / "requirements" / "LLR").mkdir(parents=True)
        (root / "requirements" / "data_dictionary").mkdir(parents=True)
        (root / "software" / "source" / "utilities" / "private" / "base").mkdir(parents=True)
        (root / "verification" / "test-cases" / "low_level" / "Utilities" / "Base_Utils" / "Util_Queue").mkdir(parents=True)
        (root / "verification" / "test-procedures" / "procedure-vectors" / "Utilities" / "Base_Utils" / "Util_Queue").mkdir(parents=True)
        (root / "verification" / "test-procedures" / "procedure-data").mkdir(parents=True)
        (root / "requirements" / "LLR" / "FAF-LLR-1323.md").write_text(QUEUE_REQUIREMENT)
        (root / "requirements" / "data_dictionary" / "function.csv").write_text(
            "FUNC_NAME,PARAM_NAME,PARAM_TYPE,PARAM_MODE,PED,PRODUCER\n"
            "Push Element operation,Queue Instance Reference,Queue*,IN,Reference to the queue instance,Queue\n"
            "Push Element operation,Element Reference,void*,IN,Element reference to be inserted into the queue,Queue\n"
            "Push Element operation,Use Non Blocking Lock,bool,IN,The operation will not succeed when true if another thread has already acquired the lock,Queue\n"
        )
        (root / "software" / "source" / "utilities" / "private" / "base" / "util_queue.c").write_text(QUEUE_SOURCE)
        (root / "verification" / "test-cases" / "low_level" / "Utilities" / "Base_Utils" / "Util_Queue" / "test_UtlQueuePush.py").write_text(
            "import pytest\n"
        )
        (root / "verification" / "test-procedures" / "procedure-vectors" / "Utilities" / "Base_Utils" / "Util_Queue" / "UtlQueuePush.rvstest").write_text(
            "<testmodel:Suite></testmodel:Suite>\n"
        )
        (root / "verification" / "test-procedures" / "procedure-data" / "data_dictionary.csv").write_text(
            "RequirementName,VerificationIdentifier,elementType,stubReference,baseDataType,leafDataType\n"
            "Push Operation,Push Operation Status,local,,uint32_t,uint32_t\n"
        )

    def test_evidence_bundle_prefers_same_module_examples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            self._create_queue_repo(root)
            discovery = scan_repository(root, keywords=["FAF-LLR-1323", "UtlQueuePush", "Mutex Lock"])
            req = RequirementInput(identifier="FAF-LLR-1323", text=QUEUE_REQUIREMENT, source_snippet="UtlQueuePush(queue, element, useNonBlockingLock)")

            bundle = build_evidence_bundle(root, req, discovery.requirement_files + discovery.source_files + discovery.dictionary_files + discovery.test_files + discovery.harness_files, resolved_requirement={
                "name": "Push Operation - Mutex Lock",
                "bold_terms": ["Push Element operation", "Mutex Lock", "Use Non Blocking Lock"],
                "matched_lines": ["FAF-LLR-1323"],
                "excerpt": "Push Operation - Mutex Lock",
            }, output_dir=root / "artifacts")

            self.assertTrue(bundle.has_requirement_evidence)
            self.assertTrue(bundle.has_source_evidence)
            self.assertTrue(bundle.has_dictionary_evidence)
            self.assertTrue(bundle.has_test_evidence or bundle.has_learning_example)
            self.assertTrue(bundle.same_function_hits or bundle.same_module_hits)
            self.assertGreaterEqual(bundle.confidence, 0.6)
            self.assertIn(bundle.recommended_mode, {"Direct", "Hybrid", "Manual"})
            self.assertTrue(bundle.supports_generation)

    def test_orchestrator_blocks_without_reusable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            (root / "requirements" / "HLR").mkdir(parents=True)
            (root / "requirements" / "LLR").mkdir(parents=True)
            (root / "requirements" / "data_dictionary").mkdir(parents=True)
            (root / "software" / "source").mkdir(parents=True)
            (root / "verification" / "test-cases").mkdir(parents=True)
            (root / "verification" / "test-procedures").mkdir(parents=True)
            (root / "requirements" / "LLR" / "FAF-LLR-1323.md").write_text(QUEUE_REQUIREMENT)

            orchestrator = VerificationOrchestrator.create(root)
            state = orchestrator.run_to_directory("FAF-LLR-1323", output_dir=root / "artifacts")

            self.assertEqual(state.get("status"), "blocked")
            self.assertEqual(state.get("evidence_status"), "blocked")
            self.assertFalse(state.get("dd_rows"))
            self.assertIn("evidence", (state.get("review_notes", "") or "").lower())

    def test_python_tests_use_evidence_backed_positive_case(self) -> None:
        dd_rows = [
            DDRow(requirement_name="Push Operation", verification_identifier="Push Operation Status", element_type="return", name="DD_push_operation_status"),
            DDRow(requirement_name="Push Operation", verification_identifier="Use Non Blocking Lock", element_type="argument", name="DD_use_non_blocking_lock"),
            DDRow(requirement_name="Push Operation", verification_identifier="Element Value", element_type="argument", name="DD_element_value"),
        ]
        behaviors = [RequirementBehavior(label="Highlighted requirement terms", description="Track bolded requirement terms from the resolved requirement text.", terms=["Push Element operation", "Mutex Lock"])]

        text = render_python_tests(
            function_name="UtlQueuePush",
            requirement_id="FAF-LLR-1323",
            component_name="Utilities/Base_Utils/Util_Queue/UtlQueuePush.rvstest",
            mappings=[],
            dd_rows=dd_rows,
            behaviors=behaviors,
            mode="Direct",
        )

        self.assertIn("Evidence-backed positive path coverage", text)
        self.assertNotIn("tc_smoke_positive", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
