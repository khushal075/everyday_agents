"""Sentiment evaluation with explicit handling of baseline abstentions.

Uncertain is not neutral: an abstention counts as a missed prediction in overall
accuracy and true-class recall/F1. Macro F1 averages the three sentiment classes
only. Coverage and accuracy among covered examples are reported separately.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from everyday_agents.core.agent import Predictor
from everyday_agents.ml.metrics import ClassMetrics, classification_metrics

from .baseline import SentimentBaseline
from .schemas import SentimentExample, SentimentOutput


_TRUE_LABELS = ("negative", "neutral", "positive")
_PREDICTED_LABELS = (*_TRUE_LABELS, "uncertain")


@dataclass(frozen=True)
class SentimentEvaluation:
    sample_count: int
    accuracy: float
    macro_f1: float
    coverage: float
    covered_accuracy: float | None
    per_class: dict[str, ClassMetrics]
    true_labels: tuple[str, ...]
    predicted_labels: tuple[str, ...]
    confusion_matrix: tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class SentimentComparison:
    learned: SentimentEvaluation
    baseline: SentimentEvaluation


def evaluate_predictor(
    predictor: Predictor[str, SentimentOutput],
    examples: Sequence[SentimentExample],
) -> SentimentEvaluation:
    """Evaluate a fixed predictor without fitting, tuning, or changing examples.

    Matrix rows use true_labels and columns use predicted_labels. No artificial
    ground-truth uncertain class is included in the macro F1 denominator.
    """
    if not examples:
        raise ValueError("Sentiment evaluation requires non-empty examples")
    if any(not isinstance(row, SentimentExample) for row in examples):
        raise TypeError("Evaluation data must contain SentimentExample records")
    actual = [row.label for row in examples]
    predicted = [predictor.predict(row.text).sentiment for row in examples]
    report = classification_metrics(actual, predicted, labels=_PREDICTED_LABELS)
    covered = [(truth, guess) for truth, guess in zip(actual, predicted) if guess != "uncertain"]
    per_class = {label: report.per_class[label] for label in _TRUE_LABELS}
    return SentimentEvaluation(
        sample_count=len(examples),
        accuracy=report.accuracy,
        macro_f1=sum(item.f1 for item in per_class.values()) / len(_TRUE_LABELS),
        coverage=len(covered) / len(examples),
        covered_accuracy=(sum(truth == guess for truth, guess in covered) / len(covered)) if covered else None,
        per_class=per_class,
        true_labels=_TRUE_LABELS,
        predicted_labels=_PREDICTED_LABELS,
        confusion_matrix=report.confusion_matrix[:len(_TRUE_LABELS)],
    )


def compare_with_baseline(
    predictor: Predictor[str, SentimentOutput],
    examples: Sequence[SentimentExample],
) -> SentimentComparison:
    """Compare fixed predictors on exactly the same held-out examples."""
    return SentimentComparison(
        learned=evaluate_predictor(predictor, examples),
        baseline=evaluate_predictor(SentimentBaseline(), examples),
    )
