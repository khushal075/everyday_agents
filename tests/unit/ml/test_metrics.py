"""Evaluate hand-calculated cases, class coverage, and input validation."""

from dataclasses import asdict
import json
import unittest

from everyday_agents.ml.metrics import classification_metrics


class ClassificationMetricTests(unittest.TestCase):
    def test_known_multiclass_example(self):
        report = classification_metrics(
            ["a", "a", "a", "b", "b", "c"],
            ["a", "a", "b", "b", "c", "c"],
        )
        self.assertEqual(report.labels, ("a", "b", "c"))
        self.assertEqual(report.confusion_matrix, ((2, 1, 0), (0, 1, 1), (0, 0, 1)))
        self.assertAlmostEqual(report.accuracy, 4 / 6)
        self.assertAlmostEqual(report.macro_f1, 59 / 90)
        self.assertEqual(report.per_class["a"].precision, 1.0)
        self.assertAlmostEqual(report.per_class["a"].recall, 2 / 3)
        self.assertAlmostEqual(report.per_class["a"].f1, 0.8)
        self.assertEqual(report.per_class["a"].support, 3)
        self.assertEqual(report.per_class["b"].f1, 0.5)
        self.assertAlmostEqual(report.per_class["c"].f1, 2 / 3)

    def test_perfect_predictions(self):
        report = classification_metrics(["positive", "negative"], ["positive", "negative"])
        self.assertEqual(report.accuracy, 1.0)
        self.assertEqual(report.macro_f1, 1.0)

    def test_completely_wrong_predictions(self):
        report = classification_metrics(["a", "b"], ["b", "a"])
        self.assertEqual(report.accuracy, 0.0)
        self.assertEqual(report.macro_f1, 0.0)

    def test_predicted_only_class_is_not_dropped(self):
        report = classification_metrics(["a", "a"], ["a", "b"])
        self.assertEqual(report.per_class["b"].support, 0)
        self.assertEqual(report.per_class["b"].recall, 0.0)
        self.assertAlmostEqual(report.macro_f1, 1 / 3)

    def test_never_predicted_class_has_zero_precision(self):
        report = classification_metrics(["a", "b"], ["a", "a"])
        self.assertEqual(report.per_class["b"].precision, 0.0)
        self.assertEqual(report.per_class["b"].f1, 0.0)

    def test_explicit_order_and_absent_classes(self):
        report = classification_metrics(["a", "b"], ["a", "b"], labels=["b", "a", "c"])
        self.assertEqual(report.labels, ("b", "a", "c"))
        self.assertEqual(report.confusion_matrix, ((1, 0, 0), (0, 1, 0), (0, 0, 0)))
        self.assertEqual(report.per_class["c"].support, 0)
        self.assertAlmostEqual(report.macro_f1, 2 / 3)

    def test_macro_f1_reveals_ignored_minority_class(self):
        report = classification_metrics(["major"] * 9 + ["minor"], ["major"] * 10)
        self.assertEqual(report.accuracy, 0.9)
        self.assertAlmostEqual(report.macro_f1, 9 / 19)
        self.assertEqual(report.per_class["minor"].recall, 0.0)

    def test_invalid_sizes_and_label_sets_are_rejected(self):
        for actual, predicted in (([], []), (["a"], [])):
            with self.subTest(actual=actual), self.assertRaises(ValueError):
                classification_metrics(actual, predicted)
        for labels in ([], ["a", "a"], ["a"]):
            with self.subTest(labels=labels), self.assertRaises(ValueError):
                classification_metrics(["a"], ["b"], labels=labels)

    def test_nonstring_and_empty_labels_are_rejected(self):
        for actual, predicted, error in (
            ("positive", ["positive"], TypeError),
            (["a"], "a", TypeError),
            ([1], ["a"], TypeError),
            (["a"], [0.5], TypeError),
            ([" "], ["a"], ValueError),
        ):
            with self.subTest(actual=actual, predicted=predicted), self.assertRaises(error):
                classification_metrics(actual, predicted)

    def test_inputs_remain_unchanged_and_report_is_serializable(self):
        actual, predicted, labels = ["b", "a"], ["b", "b"], ["b", "a"]
        report = classification_metrics(actual, predicted, labels=labels)
        self.assertEqual((actual, predicted, labels), (["b", "a"], ["b", "b"], ["b", "a"]))
        payload = json.loads(json.dumps(asdict(report), allow_nan=False))
        self.assertEqual(payload["accuracy"], 0.5)
        self.assertEqual(payload["labels"], ["b", "a"])


if __name__ == "__main__":
    unittest.main()
