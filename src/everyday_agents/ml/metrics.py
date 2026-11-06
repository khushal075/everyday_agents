"""Dependency-free metrics for single-label classification with string labels.

Use this for discrete predictions, not polarity values or confidence scores.
Ranking, regression, and workflow success need separate evaluation measures.
"""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ClassMetrics:
    """Class scores in [0, 1]; support is the number of true examples."""

    precision: float
    recall: float
    f1: float
    support: int


@dataclass(frozen=True)
class ClassificationMetrics:
    """Evaluation summary with explicit confusion-matrix label order.

    Matrix rows represent true labels; columns represent predicted labels.
    Macro F1 is the unweighted mean across all labels in this report.
    """

    accuracy: float
    macro_f1: float
    labels: tuple[str, ...]
    per_class: dict[str, ClassMetrics]
    confusion_matrix: tuple[tuple[int, ...], ...]


def _validate_labels(values: Sequence[str], name: str) -> None:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must be a sequence of string labels, not a string")
    for value in values:
        if not isinstance(value, str):
            raise TypeError(f"{name} must contain only string labels")
        if not value.strip():
            raise ValueError(f"{name} must not contain empty labels")


def classification_metrics(
    y_true: Sequence[str],
    y_pred: Sequence[str],
    *,
    labels: Sequence[str] | None = None,
) -> ClassificationMetrics:
    """Evaluate aligned true/predicted labels without modifying either input.

    Inputs must be non-empty and equal in length. By default, labels are the
    sorted union of observed true and predicted classes. Explicit labels set
    matrix order and must be unique and include every observed class. Additional
    unobserved classes are allowed and contribute zero to macro F1.

    Undefined precision, recall, or F1 is reported as zero (zero-division=0).
    Predicted-only classes remain in the report. This function does not choose
    thresholds, interpret an uncertain label, or remove abstained predictions:
    every supplied label is treated as a class. Callers must define a consistent
    ground-truth taxonomy or evaluate abstention separately.
    """
    _validate_labels(y_true, "y_true")
    _validate_labels(y_pred, "y_pred")
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred must have the same length")
    if len(y_true) == 0:
        raise ValueError("Cannot evaluate empty predictions")

    observed = set(y_true) | set(y_pred)
    if labels is None:
        ordered = tuple(sorted(observed))
    else:
        _validate_labels(labels, "labels")
        ordered = tuple(labels)
        if not ordered or len(set(ordered)) != len(ordered):
            raise ValueError("labels must be non-empty and unique")
        if not observed.issubset(ordered):
            raise ValueError("labels must include every observed true and predicted class")

    positions = {label: index for index, label in enumerate(ordered)}
    matrix = [[0] * len(ordered) for _ in ordered]
    for actual, predicted in zip(y_true, y_pred):
        matrix[positions[actual]][positions[predicted]] += 1

    per_class: dict[str, ClassMetrics] = {}
    correct = 0
    for index, label in enumerate(ordered):
        true_positive = matrix[index][index]
        support = sum(matrix[index])
        predicted_count = sum(row[index] for row in matrix)
        precision = true_positive / predicted_count if predicted_count else 0.0
        recall = true_positive / support if support else 0.0
        # 2TP / (true count + predicted count) is equivalent to harmonic F1.
        denominator = support + predicted_count
        f1 = 2 * true_positive / denominator if denominator else 0.0
        per_class[label] = ClassMetrics(precision, recall, f1, support)
        correct += true_positive

    return ClassificationMetrics(
        accuracy=correct / len(y_true),
        macro_f1=sum(item.f1 for item in per_class.values()) / len(ordered),
        labels=ordered,
        per_class=per_class,
        confusion_matrix=tuple(tuple(row) for row in matrix),
    )
