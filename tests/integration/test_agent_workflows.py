"""Exercise assembled sentiment workflows and the user-facing demo."""

import json
from pathlib import Path
import subprocess
import sys
import unittest

from everyday_agents.agents.sentiment import create_agent
from everyday_agents.agents.sentiment.schemas import SentimentPrediction
from everyday_agents.agents.sentiment.tools import FeedbackTool


_ROOT = Path(__file__).resolve().parents[2]


class SentimentWorkflowTests(unittest.TestCase):
    def test_factory_runs_all_routing_paths_and_retains_records(self):
        tool = FeedbackTool()
        agent = create_agent(tool=tool)
        for text, sentiment, action, status in (
            ("I love this helpful product", "positive", "record", "recorded"),
            ("This is terrible and broken", "negative", "prepare_review", "pending_review"),
            ("Delivery arrived today", "uncertain", "prepare_review", "pending_review"),
        ):
            with self.subTest(text=text):
                run = agent.run(text)
                self.assertEqual(run.prediction.sentiment, sentiment)
                self.assertEqual(run.decision.action, action)
                self.assertEqual(run.result.details["status"], status)
                self.assertEqual(run.result.details["text"], text)
                self.assertTrue(run.result.success)
                self.assertTrue(tool.verify(run.result))
        self.assertEqual(len(tool.records), 3)

    def test_default_factories_do_not_share_stores(self):
        first, second = create_agent(), create_agent()
        run = first.run("good")
        self.assertTrue(first.tool.verify(run.result))
        self.assertFalse(second.tool.verify(run.result))

    def test_predictor_can_be_replaced_without_changing_workflow(self):
        class FixedPredictor:
            def predict(self, input_data: str) -> SentimentPrediction:
                return SentimentPrediction("negative", -0.5, 1, 3)
        agent = create_agent(predictor=FixedPredictor())
        run = agent.run("A domain-specific input")
        self.assertEqual(run.prediction.polarity, -0.5)
        self.assertEqual(run.decision.action, "prepare_review")
        self.assertTrue(run.result.success)

    def test_invalid_input_does_not_create_records(self):
        tool = FeedbackTool()
        with self.assertRaises(ValueError):
            create_agent(tool=tool).run("  ")
        self.assertEqual(tool.records, ())

    def test_demo_emits_three_completed_runs(self):
        result = subprocess.run(
            [sys.executable, str(_ROOT / "examples/sentiment_demo.py")],
            cwd=_ROOT, capture_output=True, text=True, check=True,
        )
        runs = json.loads(result.stdout)
        self.assertEqual(len(runs), 3)
        self.assertEqual([r["prediction"]["sentiment"] for r in runs],
                         ["positive", "negative", "uncertain"])
        self.assertTrue(all(r["result"]["success"] for r in runs))

    def test_demo_accepts_custom_text_and_rejects_empty_text(self):
        command = [sys.executable, str(_ROOT / "examples/sentiment_demo.py"), "--text"]
        result = subprocess.run(command + ["terrible"], cwd=_ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)[0]["decision"]["action"], "prepare_review")
        invalid = subprocess.run(command + ["  "], cwd=_ROOT, capture_output=True, text=True)
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("must not be empty", invalid.stderr)
        self.assertEqual(invalid.stdout, "")


if __name__ == "__main__":
    unittest.main()
