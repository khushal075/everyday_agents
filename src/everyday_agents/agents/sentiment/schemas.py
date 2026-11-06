"""Sentiment-specific outputs; score interpretation stays outside core."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SentimentPrediction:
    """Lexicon sentiment with polarity in [-1, 1], not model confidence.

    Uncertain means either no recognised sentiment or balanced evidence.
    It does not establish that the text is neutral.
    """

    sentiment: Literal["positive", "negative", "uncertain"]
    polarity: float
    positive_matches: int
    negative_matches: int


@dataclass(frozen=True)
class FeedbackRecord:
    """A local record created by the sentiment tool, not an external ticket."""

    record_id: str
    text: str
    status: Literal["recorded", "pending_review"]
    reason: str
