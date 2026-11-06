"""Translate sentiment labels into actions without executing tools."""

from everyday_agents.core.schemas import Decision

from .schemas import SentimentOutput


class SentimentPolicy:
    """Record positive/neutral feedback; prepare negative or uncertain text for review.

    Routing uses the predicted label, not a confidence threshold: the baseline's
    polarity is not confidence. Unsupported labels fail instead of silently
    recording feedback.
    """

    def decide(self, prediction: SentimentOutput) -> Decision:
        if prediction.sentiment == "positive":
            return Decision(
                action="record",
                reason="Positive feedback can be recorded without a review item",
            )
        if prediction.sentiment == "neutral":
            return Decision(
                action="record",
                reason="Neutral feedback can be recorded without a review item",
            )
        if prediction.sentiment == "negative":
            return Decision(
                action="prepare_review",
                reason="Negative feedback needs human review",
            )
        if prediction.sentiment == "uncertain":
            return Decision(
                action="prepare_review",
                reason="Sentiment is uncertain and needs human review",
            )
        raise ValueError(f"Unsupported sentiment label: {prediction.sentiment!r}")
