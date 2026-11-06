"""Adapter between a fitted sklearn pipeline and the sentiment agent."""

from typing import cast

from sklearn.pipeline import Pipeline
from sklearn.utils.validation import check_is_fitted

from .schemas import LearnedSentimentPrediction, SentimentLabel


class LearnedSentimentPredictor:
    """Predict three sentiment classes, without executing policy or tools.

    Probabilities are model estimates, not calibrated guarantees. No abstention
    threshold is applied: even unknown vocabulary yields a class prediction.
    """

    def __init__(self, pipeline: Pipeline) -> None:
        check_is_fitted(pipeline)
        if set(pipeline.classes_) != {"positive", "negative", "neutral"}:
            raise ValueError("Sentiment model must contain positive, negative, and neutral classes")
        self.pipeline = pipeline

    def predict(self, input_data: str) -> LearnedSentimentPrediction:
        if not isinstance(input_data, str):
            raise TypeError("Sentiment input must be a string")
        if not input_data.strip():
            raise ValueError("Sentiment input must not be empty")
        values = self.pipeline.predict_proba([input_data])[0]
        probabilities = {
            cast(SentimentLabel, str(label)): float(value)
            for label, value in zip(self.pipeline.classes_, values)
        }
        sentiment = max(probabilities, key=lambda label: probabilities[label])
        return LearnedSentimentPrediction(sentiment, probabilities)
