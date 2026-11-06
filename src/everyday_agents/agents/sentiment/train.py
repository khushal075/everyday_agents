"""Train, evaluate on validation data, and optionally save a sentiment predictor.

Run from the repository root:
    uv run python -m everyday_agents.agents.sentiment.train --text "Great service"
"""

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from everyday_agents.ml.datasets import load_dataset
from everyday_agents.ml.splitting import DatasetSplit, split_dataset

from .evaluation import compare_with_baseline
from .features import build_vectorizer
from .predictor import LearnedSentimentPredictor, save_predictor
from .schemas import SentimentExample


def validate_record(record: Mapping[str, Any]) -> None:
    """Validate domain fields; the shared loader adds file and line context."""
    SentimentExample(text=record["text"], label=record["label"])


def load_examples(source: str | Path) -> list[SentimentExample]:
    records = load_dataset(source, required_fields=("text", "label"), validator=validate_record)
    return [SentimentExample(text=row["text"], label=row["label"]) for row in records]


class SentimentTrainer:
    """Implement Trainer for labelled text, returning a fitted predictor.

    Pass training examples only. All three classes must be represented. No
    feature fitting occurs before this method receives the training partition.
    """

    def __init__(self, *, seed: int = 42) -> None:
        self.seed = seed

    def train(self, training_data: Sequence[SentimentExample]) -> LearnedSentimentPredictor:
        if not training_data:
            raise ValueError("Sentiment training requires non-empty data")
        if any(not isinstance(row, SentimentExample) for row in training_data):
            raise TypeError("Training data must contain SentimentExample records")
        if {row.label for row in training_data} != {"positive", "negative", "neutral"}:
            raise ValueError("Training partition must contain positive, negative, and neutral examples")
        pipeline = Pipeline([
            ("tfidf", build_vectorizer()),
            ("classifier", LogisticRegression(max_iter=1000, random_state=self.seed)),
        ])
        pipeline.fit([row.text for row in training_data], [row.label for row in training_data])
        return LearnedSentimentPredictor(pipeline)


@dataclass(frozen=True)
class SentimentTrainingResult:
    predictor: LearnedSentimentPredictor
    splits: DatasetSplit[SentimentExample]


def train_from_file(source: str | Path, *, seed: int = 42) -> SentimentTrainingResult:
    """Load, split 80/10/10, and fit on training only.

    Validation and test examples are returned untouched for later evaluation.
    Splitting is row-level, not stratified or group-aware. Missing training
    classes raise; larger/grouped datasets need an appropriate split strategy.
    """
    splits = split_dataset(load_examples(source), seed=seed)
    predictor = SentimentTrainer(seed=seed).train(splits.train)
    return SentimentTrainingResult(predictor, splits)


def training_report(
    source: str | Path,
    *,
    seed: int = 42,
    output: str | Path | None = None,
    model_version: str = "1.0.0",
    evaluate_test: bool = False,
    text: str | None = None,
) -> dict[str, Any]:
    """Train and report validation results, optionally test and save.

    Evaluation never selects parameters automatically. Existing artifact paths
    are rejected before training; errors propagate to the caller.
    """
    if output is not None and (Path(output).exists() or Path(output).is_symlink()):
        raise FileExistsError(f"Artifact destination already exists: {output}")
    trained = train_from_file(source, seed=seed)
    report: dict[str, Any] = {
        "training_rows": len(trained.splits.train),
        "validation_rows": len(trained.splits.validation),
        "test_rows": len(trained.splits.test),
        "classes": [str(label) for label in trained.predictor.pipeline.classes_],
    }
    report["validation"] = asdict(compare_with_baseline(trained.predictor, trained.splits.validation))
    if evaluate_test:
        report["test"] = asdict(compare_with_baseline(trained.predictor, trained.splits.test))
    if text is not None:
        report["prediction"] = asdict(trained.predictor.predict(text))
    if output is not None:
        report["artifact"] = str(save_predictor(
            trained.predictor, output, model_version=model_version,
        ))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a demo TF-IDF sentiment model")
    parser.add_argument("--data", type=Path, default=Path("data/samples/sentiment/feedback.jsonl"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--text", help="Optionally predict one text after training")
    parser.add_argument("--output", type=Path, help="New artifact directory; existing paths are refused")
    parser.add_argument("--model-version", default="1.0.0")
    parser.add_argument("--evaluate-test", action="store_true", help="Explicit final test evaluation; do not use for tuning")
    args = parser.parse_args()
    try:
        report = training_report(
            args.data, seed=args.seed, output=args.output, model_version=args.model_version,
            evaluate_test=args.evaluate_test, text=args.text,
        )
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
