"""Check training/inference, leakage boundaries, and agent compatibility."""

from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from sklearn.exceptions import NotFittedError
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from everyday_agents.agents.sentiment import create_agent
from everyday_agents.agents.sentiment.features import build_vectorizer
from everyday_agents.agents.sentiment.policy import SentimentPolicy
from everyday_agents.agents.sentiment.predictor import LearnedSentimentPredictor
from everyday_agents.agents.sentiment.schemas import SentimentExample, LearnedSentimentPrediction
from everyday_agents.agents.sentiment.train import SentimentTrainer, load_examples, train_from_file
from everyday_agents.ml.splitting import split_dataset


_ROOT = Path(__file__).resolve().parents[3]
_SAMPLE = _ROOT / "data/samples/sentiment/feedback.jsonl"


class SentimentTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.examples = load_examples(_SAMPLE)
        cls.trained = train_from_file(_SAMPLE)

    def test_sample_is_balanced_and_valid_without_duplicate_text(self):
        self.assertEqual(len(self.examples), 72)
        self.assertEqual(len({row.text.casefold() for row in self.examples}), 72)
        for label in ("positive", "negative", "neutral"):
            self.assertEqual(sum(row.label == label for row in self.examples), 24)

    def test_probabilities_cover_all_classes_and_sum_to_one(self):
        output = self.trained.predictor.predict("Great helpful service")
        self.assertEqual(set(output.probabilities), {"positive", "negative", "neutral"})
        self.assertTrue(all(0 <= value <= 1 for value in output.probabilities.values()))
        self.assertAlmostEqual(sum(output.probabilities.values()), 1.0)
        self.assertEqual(output.sentiment, max(output.probabilities, key=output.probabilities.get))
        self.assertNotIn("positive_matches", asdict(output))
        json.dumps(asdict(output), allow_nan=False)

    def test_vocabulary_is_fitted_only_on_training_rows(self):
        # Give every row one unique token, then confirm held-out tokens never
        # enter the fitted vectorizer's vocabulary.
        examples = [SentimentExample(f"token{i} sample {label}", label)
                    for i, label in enumerate(["positive", "negative", "neutral"] * 20)]
        split = split_dataset(examples)
        predictor = SentimentTrainer().train(split.train)
        vocabulary = predictor.pipeline.named_steps["tfidf"].vocabulary_
        for row in split.train:
            self.assertIn(row.text.split()[0], vocabulary)
        for row in split.validation + split.test:
            self.assertNotIn(row.text.split()[0], vocabulary)
        before = dict(vocabulary)
        predictor.predict("neverobservedvocabulary")
        self.assertEqual(vocabulary, before)

    def test_training_result_returns_untouched_heldout_rows(self):
        expected = split_dataset(self.examples)
        self.assertEqual(self.trained.splits, expected)
        self.assertEqual((len(expected.train), len(expected.validation), len(expected.test)), (58, 7, 7))

    def test_neutral_predictions_are_recorded_and_negative_are_reviewed(self):
        policy = SentimentPolicy()
        for sentiment, expected in (("neutral", "record"), ("negative", "prepare_review")):
            probabilities = {label: float(label == sentiment) for label in ("positive", "negative", "neutral")}
            prediction = LearnedSentimentPrediction(sentiment, probabilities)
            self.assertEqual(policy.decide(prediction).action, expected)
        text = "This is terrible and broken"
        prediction = self.trained.predictor.predict(text)
        run = create_agent(predictor=self.trained.predictor).run(text)
        self.assertEqual(run.prediction, prediction)
        self.assertEqual(run.decision, policy.decide(prediction))
        self.assertTrue(run.result.success)
        expected_status = "pending_review" if prediction.sentiment == "negative" else "recorded"
        self.assertEqual(run.result.details["status"], expected_status)

    def test_invalid_examples_are_rejected(self):
        for text, label in (("", "positive"), ("  ", "neutral"), (None, "negative"),
                            ("text", "uncertain"), ("text", ["positive"])):
            with self.subTest(text=text, label=label), self.assertRaises(ValueError):
                SentimentExample(text, label)

    def test_invalid_training_partitions_are_rejected(self):
        for examples in ([], [SentimentExample("good", "positive")]):
            with self.subTest(examples=examples), self.assertRaises(ValueError):
                SentimentTrainer().train(examples)
        with self.assertRaises(TypeError):
            SentimentTrainer().train([{"text": "good", "label": "positive"}])

    def test_invalid_file_labels_have_line_context(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.jsonl"
            path.write_text('{"text":"hello", "label":"uncertain"}\n')
            with self.assertRaisesRegex(ValueError, "line 1: validation failed"):
                load_examples(path)

    def test_predictor_rejects_unfitted_model_and_invalid_text(self):
        pipeline = Pipeline([("tfidf", build_vectorizer()), ("classifier", LogisticRegression())])
        with self.assertRaises(NotFittedError):
            LearnedSentimentPredictor(pipeline)
        with self.assertRaises(ValueError):
            self.trained.predictor.predict("  ")
        with self.assertRaises(TypeError):
            self.trained.predictor.predict(None)

    def test_training_command_emits_summary_and_prediction(self):
        result = subprocess.run(
            [sys.executable, "-m", "everyday_agents.agents.sentiment.train", "--data", str(_SAMPLE),
             "--text", "Great helpful product"], cwd=_ROOT, text=True, capture_output=True, check=True,
        )
        output = json.loads(result.stdout)
        self.assertEqual(output["training_rows"], 58)
        self.assertEqual(output["validation_rows"], 7)
        self.assertEqual(output["test_rows"], 7)
        self.assertEqual(set(output["prediction"]["probabilities"]), {"positive", "negative", "neutral"})


if __name__ == "__main__":
    unittest.main()
