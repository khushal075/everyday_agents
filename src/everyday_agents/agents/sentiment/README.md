# Sentiment baseline

Status: the prediction component, policy, and in-memory feedback tool are
implemented. The end-to-end agent factory and runnable demo are not implemented yet.

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

## Decision policy

`SentimentPolicy.decide(prediction)` selects an action and provides a reason:

| Predicted sentiment | Action |
| --- | --- |
| positive | `record` |
| negative | `prepare_review` |
| uncertain | `prepare_review` |

The policy uses the label, without applying confidence thresholds to polarity.
Unknown labels raise `ValueError`. The policy does not execute tools, save
feedback, or modify the prediction. Tool execution is a separate step.

## Feedback tool

`FeedbackTool.execute(text, decision)` creates an in-memory `FeedbackRecord`:

- `record` produces status `recorded`.
- `prepare_review` produces status `pending_review`.

Each record contains a unique ID, the original text, status, and decision reason.
The returned `ActionResult` includes those fields. `verify(result)` compares all
reported fields with the stored record; a fabricated or modified result fails.
`tool.records` provides an insertion-ordered snapshot for inspection.

Empty/non-text inputs, unsupported actions, and non-empty action parameters are
rejected before storage. Repeated executions create separate records; there is
no automatic deduplication. Records belong to one tool instance and disappear
when it is discarded. Nothing is saved to disk, sent, or routed externally.
