"""Validate shared contracts without prescribing domain prediction formats."""

from dataclasses import asdict, dataclass
import json
import unittest

from everyday_agents.core.schemas import ActionResult, AgentRun, Decision


@dataclass(frozen=True)
class SentimentOutput:
    sentiment: str
    polarity: float


class SchemaTests(unittest.TestCase):
    def test_run_accepts_a_score_directly(self):
        run = AgentRun[float](
            0.8, Decision("review", "Score meets review threshold"), ActionResult(True)
        )
        self.assertEqual(run.prediction, 0.8)

    def test_run_preserves_domain_specific_output(self):
        prediction = SentimentOutput("negative", -0.8)
        run = AgentRun[SentimentOutput](
            prediction, Decision("review", "Negative feedback"), ActionResult(True)
        )
        self.assertIs(run.prediction, prediction)
        self.assertEqual(run.prediction.sentiment, "negative")

    def test_run_accepts_a_ranking_without_label_or_score(self):
        ranking = ["job-3", "job-1"]
        run = AgentRun[list[str]](
            ranking, Decision("shortlist", "Best preference matches"), ActionResult(True)
        )
        self.assertEqual(run.prediction, ranking)

    def test_decision_requires_action_and_reason(self):
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

    def test_failed_run_with_domain_dataclass_can_be_serialized(self):
        run = AgentRun(
            SentimentOutput("negative", -0.8),
            Decision("prepare_review", "Negative feedback"),
            ActionResult(False, error="Review storage unavailable"),
        )
        payload = json.loads(json.dumps(asdict(run), allow_nan=False))
        self.assertFalse(payload["result"]["success"])
        self.assertEqual(payload["result"]["error"], "Review storage unavailable")
        self.assertEqual(payload["prediction"], {"sentiment": "negative", "polarity": -0.8})


if __name__ == "__main__":
    unittest.main()
