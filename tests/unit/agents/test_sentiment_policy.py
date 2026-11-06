"""Check sentiment routing independently and against baseline outputs."""

from dataclasses import asdict
import unittest
from typing import Literal, cast

from everyday_agents.agents.sentiment.baseline import SentimentBaseline
from everyday_agents.agents.sentiment.policy import SentimentPolicy
from everyday_agents.agents.sentiment.schemas import SentimentPrediction


class SentimentPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = SentimentPolicy()

    def test_positive_feedback_is_recorded(self):
        decision = self.policy.decide(SentimentPrediction("positive", 1.0, 2, 0))
        self.assertEqual(decision.action, "record")
        self.assertIn("Positive", decision.reason)
        self.assertEqual(decision.parameters, {})

    def test_negative_feedback_requires_review(self):
        decision = self.policy.decide(SentimentPrediction("negative", -1.0, 0, 2))
        self.assertEqual(decision.action, "prepare_review")
        self.assertIn("Negative", decision.reason)

    def test_uncertain_feedback_requires_review(self):
        decision = self.policy.decide(SentimentPrediction("uncertain", 0.0, 0, 0))
        self.assertEqual(decision.action, "prepare_review")
        self.assertIn("uncertain", decision.reason)

    def test_low_positive_polarity_is_not_treated_as_low_confidence(self):
        decision = self.policy.decide(SentimentPrediction("positive", 1 / 21, 11, 10))
        self.assertEqual(decision.action, "record")

    def test_unsupported_label_is_rejected(self):
        # Simulate invalid external data despite the Literal type annotation.
        label = cast(Literal["positive", "negative", "uncertain"], "unknown")
        with self.assertRaisesRegex(ValueError, "Unsupported sentiment label"):
            self.policy.decide(SentimentPrediction(label, 0.0, 0, 0))

    def test_policy_does_not_modify_prediction(self):
        prediction = SentimentPrediction("negative", -1.0, 0, 1)
        before = asdict(prediction)
        self.policy.decide(prediction)
        self.assertEqual(asdict(prediction), before)

    def test_baseline_outputs_route_as_expected(self):
        baseline = SentimentBaseline()
        for text, expected in (
            ("I love this helpful product", "record"),
            ("This is terrible and broken", "prepare_review"),
            ("Delivery arrived today", "prepare_review"),
            ("Good design but bad delivery", "prepare_review"),
        ):
            with self.subTest(text=text):
                decision = self.policy.decide(baseline.predict(text))
                self.assertEqual(decision.action, expected)
                self.assertTrue(decision.reason.strip())


if __name__ == "__main__":
    unittest.main()
