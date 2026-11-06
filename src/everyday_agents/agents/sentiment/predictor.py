"""Adapter between a fitted sklearn pipeline and the sentiment agent."""

from importlib.metadata import version
from pathlib import Path
import sys
from typing import cast

import joblib

from sklearn.pipeline import Pipeline
from sklearn.utils.validation import check_is_fitted

from everyday_agents.ml.artifacts import LoadedArtifact, ModelMetadata, load_artifact, save_artifact

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


_MODEL_NAME = "sentiment-tfidf-logistic-regression"


def _runtime_versions() -> dict[str, str]:
    return {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        **{name: version(name) for name in ("scikit-learn", "numpy", "scipy", "joblib")},
    }


def _serialize_pipeline(pipeline: Pipeline, path: Path) -> None:
    joblib.dump(
        {"format_version": 1, "runtime_versions": _runtime_versions(), "pipeline": pipeline},
        path, compress=3,
    )


def _deserialize_pipeline(path: Path) -> Pipeline:
    # joblib deserialization executes code: use only artifacts from a trusted
    # source. Compatibility checks below are not a security boundary.
    bundle = joblib.load(path)
    if not isinstance(bundle, dict) or set(bundle) != {"format_version", "runtime_versions", "pipeline"}:
        raise ValueError("Invalid sentiment model bundle")
    if type(bundle["format_version"]) is not int or bundle["format_version"] != 1:
        raise ValueError("Unsupported sentiment model bundle version")
    if bundle["runtime_versions"] != _runtime_versions():
        raise ValueError("Model runtime versions differ; recreate the training environment with uv.lock")
    if not isinstance(bundle["pipeline"], Pipeline):
        raise ValueError("Sentiment artifact must contain a sklearn Pipeline")
    return bundle["pipeline"]


def save_predictor(
    predictor: LearnedSentimentPredictor,
    destination: str | Path,
    *,
    model_version: str = "1.0.0",
) -> Path:
    """Save fitted TF-IDF and classifier together, refusing existing directories.

    The payload records Python major/minor and exact sklearn/numpy/scipy/joblib
    versions. Keep uv.lock with the training recipe to reconstruct that runtime.
    """
    metadata = ModelMetadata(
        model_name=_MODEL_NAME, model_version=model_version,
        input_format="One non-empty text string",
        output_format="positive/negative/neutral label and three class probabilities",
    )
    return save_artifact(
        predictor.pipeline, destination, metadata, serializer=_serialize_pipeline,
    )


def load_predictor(source: str | Path) -> LoadedArtifact[LearnedSentimentPredictor]:
    """Load a trusted local model using the same runtime as training.

    Never use this loader for untrusted joblib artifacts. Loading may execute
    code before format/version checks. A compatible, fitted pipeline is required.
    """
    loaded = load_artifact(source, deserializer=_deserialize_pipeline)
    if loaded.metadata.model_name != _MODEL_NAME:
        raise ValueError("Artifact metadata does not identify a sentiment model")
    return LoadedArtifact(LearnedSentimentPredictor(loaded.model), loaded.metadata)
