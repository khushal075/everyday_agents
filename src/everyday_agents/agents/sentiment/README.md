# Sentiment baseline

Status: rules-based and learned predictors, validation comparison, and model
artifact save/load are implemented. The unified project CLI is the next step.

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
| neutral (learned model) | `record` |
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

## Run the complete agent

From the repository root, after `uv sync`:

```sh
uv run python examples/sentiment_demo.py
uv run python examples/sentiment_demo.py --text "This is terrible"
uv run python examples/sentiment_demo.py --text "Great service" --text "Delivery arrived"
```

The demo prints completed runs as a JSON array. Each run contains its prediction,
decision, and verified action result. It does not train a model or write files.

```python
from everyday_agents.agents.sentiment import create_agent

agent = create_agent()
run = agent.run("This is terrible")
print(run.decision.action)  # prepare_review
print(run.result.success)   # True
```

Each factory call creates its own in-memory tool. An existing tool or compatible
predictor can be passed using `create_agent(tool=..., predictor=...)`.

## Train a learned predictor

```sh
uv sync
uv run python -m everyday_agents.agents.sentiment.train --text "Great helpful service"
```

This loads the 72 synthetic labelled examples, splits them into 58 training, 7
validation, and 7 test rows (seed 42), and fits TF-IDF plus logistic regression
on training rows only. Unigrams and bigrams are used, without removing negation
words. It prints split counts, validation comparison, and an optional prediction.
It does not evaluate the test partition unless `--evaluate-test` is supplied.
These tiny synthetic splits do not establish real-world accuracy.

```python
from everyday_agents.agents.sentiment import create_agent
from everyday_agents.agents.sentiment.train import train_from_file

trained = train_from_file("data/samples/sentiment/feedback.jsonl")
agent = create_agent(predictor=trained.predictor)
run = agent.run("This is terrible and broken")
print(run.prediction.probabilities)
```

The learned model predicts positive, negative, or neutral. Its output is
`LearnedSentimentPrediction`, separate from baseline polarity and word counts.
Probabilities are model estimates, not calibrated confidence. No low-confidence
threshold is applied; unknown vocabulary still produces a class prediction.
Neutral feedback is recorded. Baseline uncertain output still requires review.

Data rows require non-empty `text` and a `label` of positive, negative, or neutral;
`data/schemas/sentiment.schema.json` documents this contract. `uncertain` is not a
ground-truth label. Training requires all three classes in the training partition.
The shared splitter is row-level and not stratified or group-aware. Related
examples or users must be grouped appropriately for real evaluations.

The synthetic examples are hand-authored and balanced (24 per class), with
related phrasing. They demonstrate code execution, not generalisation or model
superiority over the baseline. Larger representative data, validation-based
model selection, and a final untouched test evaluation are still required.

## Validation and model artifacts

Train, compare fixed models on validation data, and save a new artifact:

```sh
uv run python -m everyday_agents.agents.sentiment.train --output artifacts/models/sentiment-v1
```

The output compares learned and baseline predictions on the same validation
rows. It includes accuracy, per-class precision/recall/F1, macro F1, and a
confusion matrix. Matrix rows are the three true sentiment labels; columns also
include uncertain. Baseline abstentions are counted as misses, never converted
to neutral. Macro F1 averages the three sentiment classes, including classes
with zero support. Coverage and accuracy among non-abstained examples are
reported separately; covered accuracy is null when coverage is zero.

Only after model choices are fixed, request the final test report explicitly:

```sh
uv run python -m everyday_agents.agents.sentiment.train --evaluate-test
```

This flag is a workflow convention, not a mechanism preventing repeated test
evaluation. Do not use test scores to tune the model or select a seed.

Load a previously saved trusted model without training:

```python
from everyday_agents.agents.sentiment import create_agent
from everyday_agents.agents.sentiment.predictor import load_predictor

loaded = load_predictor("artifacts/models/sentiment-v1")
agent = create_agent(predictor=loaded.model)
print(agent.run("Great helpful service"))
```

Each artifact contains `model` (compressed joblib, including fitted TF-IDF and
classifier) and `metadata.json`. Existing destinations are refused. The payload
records Python major/minor and sklearn, numpy, scipy, and joblib versions; loading
requires matching versions. Recreate the training environment with `uv.lock`.
These checks happen after deserialization and are not a security boundary.
Joblib may execute code: load only artifacts you trust. See the
[scikit-learn persistence guidance](https://scikit-learn.org/stable/model_persistence.html).

Prediction probabilities, labels, and policy decisions are preserved by save/load.
An artifact contains the trained pipeline, not feedback records; those remain
in memory. Saving does not imply that a model passed a quality threshold or
outperformed the baseline.
