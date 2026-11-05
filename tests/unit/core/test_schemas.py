"""Validate the shared contracts without introducing third-party dependencies."""

from dataclasses import asdict
import json
import unittest

from everyday_agents.core.schemas import ActionResult, AgentRun, Decision, Prediction


class SchemaTests(unittest.TestCase):
    def test_scores_keep_domain_specific_scales(self):
        polarity = Prediction("negative", -0.8, "Polarity from -1 to 1")
        match = Prediction("suitable", 92.0, "Personal match from 0 to 100")
        self.assertEqual(polarity.score, -0.8)
        self.assertEqual(match.score, 92.0)

    def test_nonfinite_scores_rejected(self):
        for score in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(score=score), self.assertRaises(ValueError):
                Prediction("unknown", score, "Example score")

    def test_score_meaning_and_identifiers_required(self):
        for arguments in ((" ", 0, "Polarity"), ("neutral", 0, " ")):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                Prediction(*arguments)
        for arguments in ((" ", "Review needed"), ("review", " ")):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                Decision(*arguments)

    def test_default_payloads_are_independent(self):
        first, second = ActionResult(True), ActionResult(True)
        first.details["id"] = "review-1"
        self.assertEqual(second.details, {})
        first_decision = Decision("review", "Uncertain prediction")
        second_decision = Decision("review", "Uncertain prediction")
        first_decision.parameters["queue"] = "feedback"
        self.assertEqual(second_decision.parameters, {})

    def test_failed_run_can_be_serialized(self):
        run = AgentRun(
            Prediction("negative", -0.8, "Polarity from -1 to 1"),
            Decision("prepare_review", "Negative feedback"),
            ActionResult(False, error="Review storage unavailable"),
        )
        payload = json.loads(json.dumps(asdict(run), allow_nan=False))
        self.assertFalse(payload["result"]["success"])
        self.assertEqual(payload["result"]["error"], "Review storage unavailable")
        self.assertEqual(payload["prediction"]["score_meaning"], "Polarity from -1 to 1")


if __name__ == "__main__":
    unittest.main()
