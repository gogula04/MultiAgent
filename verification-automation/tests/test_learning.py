from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from verification_automation.learning import learn_from_run
from verification_automation.learning_store import LearningStore


class LearningLoopTests(unittest.TestCase):
    def test_learning_store_records_examples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "learning"
            store = LearningStore(root)
            record = {
                "requirement_identifier": "FAF-LLR-1323",
                "requirement_name": "Push Operation - Mutex Lock",
                "mode": "Hybrid",
                "outcome": "verified",
            }

            run_path = store.record_run(record)
            gold_path = store.record_gold_example(record)
            summary_path = store.write_learning_summary("# Learning Summary\n")

            self.assertTrue(run_path.exists())
            self.assertTrue(gold_path.exists())
            self.assertTrue(summary_path.exists())
            self.assertIn("FAF-LLR-1323", run_path.read_text())
            self.assertEqual(len(store.load_recent_examples()), 1)

    def test_learning_agent_records_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            state = {
                "requirement_identifier": "FAF-LLR-1323",
                "requirement_name": "Push Operation - Mutex Lock",
                "mode": "Direct",
                "status": "blocked",
                "review_status": "not reviewed",
                "review_notes": "Requirement could not be resolved.",
                "learning_status": "",
                "learning_summary_text": "",
                "learning_record": {},
                "learning_artifacts": {},
                "learning_store_path": "",
                "artifacts": {},
                "test_results": {},
                "coverage": [],
                "failure_classification": [],
                "unresolved": [],
                "manual_review": [],
                "proof_report": {},
                "logs": [],
            }

            updated = learn_from_run(state, output_dir)

            self.assertEqual(updated["learning_status"], "recorded")
            self.assertIn("learning_summary_text", updated)
            self.assertIn("learning/run_history.jsonl", updated["learning_artifacts"])
            self.assertTrue(Path(updated["learning_artifacts"]["learning/run_history.jsonl"]).exists())
            self.assertTrue(updated["artifacts"])
            self.assertIn("FAF-LLR-1323", json.dumps(updated["learning_record"]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
