"""Check domain evaluation without confusing neutral sentiment and abstention."""

from dataclasses import asdict, dataclass
import json
import unittest

from everyday_agents.agents.sentiment.evaluation import compare_with_baseline, evaluate_predictor
from everyday_agents.agents.sentiment.schemas import SentimentExample


@dataclass
class Output:
    sentiment: str


class FixedPredictor:
    def __init__(self, predictions):
        self.predictions = predictions
        self.calls = []

    def predict(self, text):
        self.calls.append(text)
        return Output(self.predictions[text])


class SentimentEvaluationTests(unittest.TestCase):
    def test_known_scores_count_abstention_as_a_miss(self):
        rows = [SentimentExample("a", "negative"), SentimentExample("b", "neutral"),
                SentimentExample("c", "positive")]
        predictor = FixedPredictor({"a": "negative", "b": "uncertain", "c": "positive"})
        report = evaluate_predictor(predictor, rows)
        self.assertAlmostEqual(report.accuracy, 2 / 3)
        self.assertAlmostEqual(report.macro_f1, 2 / 3)
        self.assertAlmostEqual(report.coverage, 2 / 3)
        self.assertEqual(report.covered_accuracy, 1.0)
        self.assertEqual(report.per_class["neutral"].support, 1)
        self.assertEqual(report.per_class["neutral"].recall, 0.0)
        self.assertEqual(report.confusion_matrix, ((1, 0, 0, 0), (0, 0, 0, 1), (0, 0, 1, 0)))
        self.assertEqual(report.true_labels, ("negative", "neutral", "positive"))
        self.assertEqual(report.predicted_labels[-1], "uncertain")

    def test_all_abstentions_have_zero_coverage_and_no_covered_accuracy(self):
        report = evaluate_predictor(FixedPredictor({"a": "uncertain"}), [SentimentExample("a", "neutral")])
        self.assertEqual(report.accuracy, 0.0)
        self.assertEqual(report.macro_f1, 0.0)
        self.assertEqual(report.coverage, 0.0)
        self.assertIsNone(report.covered_accuracy)
        json.dumps(asdict(report), allow_nan=False)

    def test_missing_true_classes_remain_in_macro_average(self):
        report = evaluate_predictor(FixedPredictor({"a": "positive"}), [SentimentExample("a", "positive")])
        self.assertEqual(report.accuracy, 1.0)
        self.assertAlmostEqual(report.macro_f1, 1 / 3)
        self.assertEqual(report.per_class["negative"].support, 0)

    def test_comparison_uses_same_examples_without_modification(self):
        rows = [SentimentExample("great", "positive"), SentimentExample("terrible", "negative"),
                SentimentExample("Delivery arrived", "neutral")]
        original = list(rows)
        predictor = FixedPredictor({row.text: row.label for row in rows})
        report = compare_with_baseline(predictor, rows)
        self.assertEqual(rows, original)
        self.assertEqual(predictor.calls, [row.text for row in rows])
        self.assertEqual(report.learned.accuracy, 1.0)
        self.assertAlmostEqual(report.baseline.accuracy, 2 / 3)
        self.assertAlmostEqual(report.baseline.coverage, 2 / 3)
        self.assertEqual(report.learned.sample_count, report.baseline.sample_count)

    def test_invalid_inputs_and_unsupported_predictions_are_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_predictor(FixedPredictor({}), [])
        with self.assertRaises(TypeError):
            evaluate_predictor(FixedPredictor({}), [{}])
        with self.assertRaises(ValueError):
            evaluate_predictor(FixedPredictor({"a": "other"}), [SentimentExample("a", "positive")])


if __name__ == "__main__":
    unittest.main()
