# Everyday Agents — v0.1.0

Small ML models connected to practical agent workflows. This release implements
one complete use case: **sentiment feedback routing**, with a rules baseline and
a trained TF-IDF + logistic regression predictor.

The agent predicts sentiment, selects an action, creates a local feedback record,
and verifies the result. Negative or uncertain feedback is prepared for review;
positive or neutral feedback is recorded. Records are in memory, with no database,
external tickets, messages, or paid API requirements.

## Quick start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). From this checkout:

```sh
uv sync --locked
uv run everyday-agents --version
uv run everyday-agents sentiment run --text "This is terrible"
```

Run commands without activating a virtual environment. For IDE integration, select
`.venv/bin/python` (`.venv/Scripts/python.exe` on Windows).

Train on the included synthetic examples, compare against the baseline on the
validation partition, and save the fitted features and model together:

```sh
uv run everyday-agents sentiment train \
  --data data/samples/sentiment/feedback.jsonl \
  --output artifacts/models/sentiment-v1
```

Choose a new output directory if that destination already exists. Run the saved
model without retraining:

```sh
uv run everyday-agents sentiment run \
  --model artifacts/models/sentiment-v1 \
  --text "Great helpful service"
```

`uv run python -m everyday_agents` supports the same arguments. Commands print one
JSON object on success; invalid input produces an error on stderr and exit code
2. The older `examples/sentiment_demo.py` remains available and prints a JSON array.

## Evaluation

Training splits rows 80/10/10 using seed 42, fits only the training partition,
and reports validation results. To request the final test report after model
choices are fixed, add `--evaluate-test` to the training command. Do not tune on
that test report or choose a seed based on its score.

To evaluate a saved model without training, supply a separate labelled holdout:

```sh
uv run everyday-agents sentiment evaluate \
  --model artifacts/models/sentiment-v1 \
  --data path/to/independent-holdout.jsonl
```

This evaluates **every supplied row**. It cannot prove independence from training
data; do not pass the full original training dataset and call it a held-out test.
See [evaluation](docs/evaluation.md) and [score definitions](docs/score-definitions.md).

## Release scope and limitations

- Sentiment: baseline, training, inference, evaluation, persistence, CLI, and tests.
- Shared `core`: contracts, one bounded execution cycle, verification, error propagation.
- Shared `ml`: training contracts, CSV/JSONL loading, splitting, classification metrics, artifacts.
- Planned: photo cleanup, job matching, expense organiser, study coach, task priority.

The 72 included examples are synthetic and small. Their results demonstrate the
pipeline, not real-world quality or consistent superiority over the baseline.
Class probabilities are uncalibrated model estimates. The baseline cannot handle
negation or sarcasm reliably, and the learned model applies no low-confidence
abstention threshold. Unknown text can still receive a sentiment prediction.

Splitting is row-level, without stratification or user/group/time safeguards.
For real data, prevent related examples from leaking across partitions. Feedback
records disappear when their tool instance or process ends. No retries, persistent
memory, human review UI, or production service deployment are included.

Model artifacts use joblib: load only files you trust, using matching runtime
versions. Artifact saving protects existing destinations but is not atomic.
See the [sentiment implementation guide](src/everyday_agents/agents/sentiment/README.md).

## Development and checks

```sh
uv run --locked python -m unittest discover -s tests -v
uv build
```

CI installs locked dependencies, runs all tests on Python 3.12/3.13/3.14, builds
distributions, and checks a wheel installed into a fresh environment. Remote CI
runs after this repository is pushed to a configured GitHub remote.

```text
src/everyday_agents/
├── core/       # Agent contracts and orchestration
├── ml/         # Shared model lifecycle helpers
└── agents/     # Domain implementations; sentiment is implemented in v0.1
```

[Getting started](docs/getting-started.md) · [Architecture](docs/architecture.md) ·
[Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)
