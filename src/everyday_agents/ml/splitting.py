"""Reproducible row-level train/validation/test splitting without ML dependencies.

This is not a stratified or group-aware splitter. Related rows (for example,
photos from the same duplicate group or records from the same user) must not
be randomly split this way if that would leak information between partitions.
Fit preprocessing on the training partition only, after splitting.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from math import floor, isclose, isfinite
from random import Random


@dataclass(frozen=True)
class DatasetSplit[RowT]:
    """Independent partition lists containing the original row objects.

    Rows are not deep-copied; mutating a row can also affect the input dataset.
    """

    train: list[RowT]
    validation: list[RowT]
    test: list[RowT]


def split_dataset[RowT](
    rows: Sequence[RowT],
    *,
    train_fraction: float = 0.8,
    validation_fraction: float = 0.1,
    test_fraction: float = 0.1,
    seed: int = 42,
    shuffle: bool = True,
) -> DatasetSplit[RowT]:
    """Assign each row position to exactly one partition without changing input.

    Fractions must be finite, in [0, 1], and sum to 1 (tolerance 1e-9).
    Counts use largest-remainder rounding, with ties resolved in the order
    train, validation, test. A zero fraction yields an empty partition. If a
    positive fraction rounds to zero, raise instead of returning an unusable
    split; provide more rows or adjust the requested fractions.

    A local seeded RNG makes shuffled assignments repeatable for the same
    ordered input and settings, without changing Python's global RNG state.
    shuffle=False preserves input order and ignores seed for assignment. This
    does not itself validate time ordering or handle temporal leakage.

    Identical or related records at different positions may enter different
    partitions. Deduplication and domain-specific grouping belong upstream.
    """
    if isinstance(rows, (str, bytes, bytearray)):
        raise TypeError("rows must be a sequence of records, not a string or bytes")
    if not rows:
        raise ValueError("Cannot split an empty dataset")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise TypeError("seed must be an integer")
    if not isinstance(shuffle, bool):
        raise TypeError("shuffle must be a boolean")

    fractions = (train_fraction, validation_fraction, test_fraction)
    for value in fractions:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError("Split fractions must be numeric")
        if not isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Split fractions must be finite and between 0 and 1")
    total = sum(fractions)
    if not isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("Split fractions must sum to 1")

    # Normalize tolerated floating-point sum differences before rounding.
    quotas = [len(rows) * (fraction / total) for fraction in fractions]
    counts = [floor(quota) for quota in quotas]
    remainder_order = sorted(range(3), key=lambda i: (-(quotas[i] - counts[i]), i))
    for index in remainder_order[:len(rows) - sum(counts)]:
        counts[index] += 1
    if any(fraction > 0 and count == 0 for fraction, count in zip(fractions, counts)):
        raise ValueError(
            "Dataset is too small for the requested fractions: a positive split "
            "would be empty; add rows or adjust fractions"
        )

    indices = list(range(len(rows)))
    if shuffle:
        Random(seed).shuffle(indices)
    train_end = counts[0]
    validation_end = train_end + counts[1]
    return DatasetSplit(
        train=[rows[i] for i in indices[:train_end]],
        validation=[rows[i] for i in indices[train_end:validation_end]],
        test=[rows[i] for i in indices[validation_end:]],
    )
