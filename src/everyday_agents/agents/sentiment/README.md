# Sentiment baseline

Status: the prediction component is implemented. The sentiment policy, tool,
and end-to-end agent are not implemented yet.

`SentimentBaseline.predict(text)` returns a `SentimentPrediction` containing:

- `sentiment`: positive, negative, or uncertain.
- `polarity`: a number from -1 to +1; not a probability or confidence.
- `positive_matches` and `negative_matches`: recognised word occurrences.

Polarity is `(positive_matches - negative_matches) / total_matches`, or zero
when no words match. Balanced positive/negative counts also produce an uncertain
label. Uncertain does not mean the text has been established as neutral.

```python
from everyday_agents.agents.sentiment.baseline import SentimentBaseline

prediction = SentimentBaseline().predict("I love this helpful product")
print(prediction)
```

This is a deterministic rules baseline, not a trained ML model. It recognises
only a small English vocabulary, matches whole words case-insensitively, and
counts repeated words. Empty input is rejected. Non-empty text without recognised
words is uncertain. It does not handle negation ("not good"), sarcasm, context,
word forms such as "loved", or multilingual sentiment reliably. A single matched
word can yield a polarity of -1 or +1 without indicating high confidence.
