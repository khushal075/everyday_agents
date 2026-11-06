"""Sentiment-specific text features, fitted only during model training."""

from sklearn.feature_extraction.text import TfidfVectorizer


def build_vectorizer() -> TfidfVectorizer:
    """Keep individual words and word pairs, including negation words.

    Return an unfitted vectorizer. The training pipeline learns vocabulary and
    IDF from training texts only; validation/test inputs only use transform.
    """
    return TfidfVectorizer(
        lowercase=True,
        ngram_range=(1, 2),
        sublinear_tf=True,
    )
