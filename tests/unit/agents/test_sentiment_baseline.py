"""Behavioural checks for the local sentiment reference predictor."""

import unittest

from everyday_agents.agents.sentiment.baseline import SentimentBaseline


class SentimentBaselineTests(unittest.TestCase):
    def setUp(self):
        self.predictor = SentimentBaseline()

    def test_clear_positive_feedback(self):
        prediction = self.predictor.predict("I LOVE this helpful product!")
        self.assertEqual(prediction.sentiment, "positive")
        self.assertEqual(prediction.polarity, 1.0)
        self.assertEqual(prediction.positive_matches, 2)
        self.assertEqual(prediction.negative_matches, 0)

    def test_clear_negative_feedback(self):
        prediction = self.predictor.predict("Terrible service; the item is broken.")
        self.assertEqual(prediction.sentiment, "negative")
        self.assertEqual(prediction.polarity, -1.0)
        self.assertEqual(prediction.negative_matches, 2)

    def test_mixed_feedback_keeps_evidence_and_direction(self):
        prediction = self.predictor.predict("Good design, great support, bad delivery.")
        self.assertEqual(prediction.sentiment, "positive")
        self.assertAlmostEqual(prediction.polarity, 1 / 3)
        self.assertEqual((prediction.positive_matches, prediction.negative_matches), (2, 1))

    def test_balanced_feedback_is_uncertain(self):
        prediction = self.predictor.predict("Good design, terrible delivery.")
        self.assertEqual(prediction.sentiment, "uncertain")
        self.assertEqual(prediction.polarity, 0.0)
        self.assertEqual((prediction.positive_matches, prediction.negative_matches), (1, 1))

    def test_unknown_text_is_uncertain_not_neutral(self):
        for text in ("Delivery arrived today", "123 !!!", "bonjour"):
            with self.subTest(text=text):
                prediction = self.predictor.predict(text)
                self.assertEqual(prediction.sentiment, "uncertain")
                self.assertEqual(prediction.polarity, 0.0)
                self.assertEqual((prediction.positive_matches, prediction.negative_matches), (0, 0))

    def test_does_not_match_sentiment_inside_other_words(self):
        prediction = self.predictor.predict("glove badly goodness")
        self.assertEqual(prediction.positive_matches + prediction.negative_matches, 0)

    def test_repeated_words_count_as_occurrences(self):
        prediction = self.predictor.predict("good good bad")
        self.assertEqual((prediction.positive_matches, prediction.negative_matches), (2, 1))
        self.assertAlmostEqual(prediction.polarity, 1 / 3)

    def test_empty_inputs_are_rejected(self):
        for text in ("", "  ", "\n\t"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.predictor.predict(text)

    def test_nonstring_inputs_are_rejected(self):
        for value in (None, 42, ["good"]):
            with self.subTest(value=value), self.assertRaises(TypeError):
                self.predictor.predict(value)


if __name__ == "__main__":
    unittest.main()
