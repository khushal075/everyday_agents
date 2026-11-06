"""Sentiment-specific outputs; score interpretation stays outside core."""

from dataclasses import dataclass
from typing import Literal, Protocol


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


type SentimentLabel = Literal["positive", "negative", "neutral"]


class SentimentOutput(Protocol):
    """Only the sentiment label is shared by baseline and learned outputs."""

    @property
    def sentiment(self) -> Literal["positive", "negative", "neutral", "uncertain"]: ...


@dataclass(frozen=True)
class LearnedSentimentPrediction:
    """Model probabilities, separate from baseline polarity and word counts.

    Probabilities cover all three trained classes and are not calibrated
    confidence guarantees. No automatic uncertain/abstention threshold is used.
    """

    sentiment: SentimentLabel
    probabilities: dict[SentimentLabel, float]


@dataclass(frozen=True)
class SentimentExample:
    """One labelled example; neutral is ground truth, uncertain is abstention."""

    text: str
    label: SentimentLabel

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("Example text must be a non-empty string")
        if not isinstance(self.label, str) or self.label not in {"positive", "negative", "neutral"}:
            raise ValueError("Example label must be positive, negative, or neutral")
