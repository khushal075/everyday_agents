"""Deterministic English lexicon baseline, with no training or dependencies.

This deliberately small baseline counts word occurrences. It does not understand
negation, sarcasm, context, or other languages. Use it to validate the workflow
and compare with a trained model, not as a calibrated sentiment classifier.
"""

import re
from typing import Literal

from .schemas import SentimentPrediction


_POSITIVE_WORDS = frozenset({
    "amazing", "awesome", "excellent", "fantastic", "good", "great",
    "happy", "helpful", "love", "perfect", "pleased", "wonderful",
})
_NEGATIVE_WORDS = frozenset({
    "angry", "awful", "bad", "broken", "disappointed", "frustrating",
    "hate", "horrible", "poor", "terrible", "unhappy", "useless",
})
_WORD_PATTERN = re.compile(r"\b[a-z]+\b", re.ASCII)


class SentimentBaseline:
    """Implement the core Predictor interface through predict(text).

    Polarity = (positive matches - negative matches) / total matches.
    Text with no matches receives zero polarity and an uncertain label.
    A high absolute polarity can result from one word; it is not confidence.
    """

    def predict(self, text: str) -> SentimentPrediction:
        if not isinstance(text, str):
            raise TypeError("Sentiment input must be a string")
        if not text.strip():
            raise ValueError("Sentiment input must not be empty")

        words = _WORD_PATTERN.findall(text.lower())
        positive = sum(word in _POSITIVE_WORDS for word in words)
        negative = sum(word in _NEGATIVE_WORDS for word in words)
        total = positive + negative
        polarity = (positive - negative) / total if total else 0.0

        sentiment: Literal["positive", "negative", "uncertain"]
        if polarity > 0:
            sentiment = "positive"
        elif polarity < 0:
            sentiment = "negative"
        else:
            sentiment = "uncertain"

        return SentimentPrediction(
            sentiment=sentiment,
            polarity=polarity,
            positive_matches=positive,
            negative_matches=negative,
        )
