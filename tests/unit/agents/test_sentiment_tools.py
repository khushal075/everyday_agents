"""Validate actual feedback actions and their verification boundaries."""

from dataclasses import replace
import unittest

from everyday_agents.agents.sentiment.baseline import SentimentBaseline
from everyday_agents.agents.sentiment.policy import SentimentPolicy
from everyday_agents.agents.sentiment.tools import FeedbackTool
from everyday_agents.core.agent import Agent
from everyday_agents.core.schemas import ActionResult, Decision


class FeedbackToolTests(unittest.TestCase):
    def setUp(self):
        self.tool = FeedbackTool()

    def test_record_action_stores_original_text_and_reason(self):
        text = "  I love this product!  "
        decision = Decision("record", "Positive feedback")
        result = self.tool.execute(text, decision)
        self.assertTrue(result.success)
        self.assertTrue(self.tool.verify(result))
        record, = self.tool.records
        self.assertEqual(record.text, text)
        self.assertEqual(record.reason, decision.reason)
        self.assertEqual(record.status, "recorded")
        self.assertEqual(result.details["record_id"], record.record_id)

    def test_review_action_prepares_a_pending_record(self):
        result = self.tool.execute("Terrible product", Decision("prepare_review", "Negative feedback"))
        self.assertEqual(result.details["status"], "pending_review")
        self.assertTrue(self.tool.verify(result))

    def test_repeated_input_creates_independent_records(self):
        decision = Decision("record", "Positive feedback")
        first = self.tool.execute("good", decision)
        snapshot = self.tool.records
        second = self.tool.execute("good", decision)
        self.assertNotEqual(first.details["record_id"], second.details["record_id"])
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(len(self.tool.records), 2)
        self.assertTrue(self.tool.verify(first))
        self.assertTrue(self.tool.verify(second))

    def test_invalid_requests_have_no_storage_side_effects(self):
        cases = [
            ("", Decision("record", "Positive"), ValueError),
            (" \n", Decision("record", "Positive"), ValueError),
            (None, Decision("record", "Positive"), TypeError),
            ("good", Decision("delete", "Unsupported"), ValueError),
            ("good", Decision("record", "Positive", {"queue": "external"}), ValueError),
        ]
        for text, decision, error in cases:
            with self.subTest(text=text, decision=decision), self.assertRaises(error):
                self.tool.execute(text, decision)
            self.assertEqual(self.tool.records, ())

    def test_modified_results_fail_verification_without_changing_storage(self):
        original = self.tool.execute("good", Decision("record", "Positive"))
        for key, value in (("text", "different"), ("status", "pending_review"),
                           ("reason", "different"), ("record_id", "unknown")):
            with self.subTest(key=key):
                altered = replace(original, details={**original.details, key: value})
                self.assertFalse(self.tool.verify(altered))
        self.assertTrue(self.tool.verify(original))
        self.assertEqual(self.tool.records[0].text, "good")

    def test_fabricated_and_unsuccessful_results_fail_verification(self):
        original = self.tool.execute("good", Decision("record", "Positive"))
        for result in (ActionResult(True), ActionResult(True, {"record_id": []}),
                       replace(original, success=False)):
            with self.subTest(result=result):
                self.assertFalse(self.tool.verify(result))
        self.assertFalse(FeedbackTool().verify(original))

    def test_mutating_result_details_does_not_mutate_record(self):
        result = self.tool.execute("good", Decision("record", "Positive"))
        result.details["text"] = "changed"
        self.assertEqual(self.tool.records[0].text, "good")
        self.assertFalse(self.tool.verify(result))

    def test_real_components_complete_both_agent_action_paths(self):
        agent = Agent(SentimentBaseline(), SentimentPolicy(), self.tool)
        for text, expected in (("good", "recorded"), ("terrible", "pending_review"),
                               ("Delivery arrived", "pending_review")):
            with self.subTest(text=text):
                run = agent.run(text)
                self.assertTrue(run.result.success)
                self.assertEqual(run.result.details["status"], expected)
        self.assertEqual(len(self.tool.records), 3)


if __name__ == "__main__":
    unittest.main()
