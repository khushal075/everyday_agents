# Examples

## Phase 1: concept learning

`concepts/` is reserved for standalone examples added progressively. No concept
implementations exist yet. Read the [learning path](../docs/learning-path.md) and
[example contract](concepts/README.md) before adding the first lesson.

## Existing sentiment reference demo

The implemented baseline demonstration remains unchanged. From the repository
root after `uv sync --locked`:

```sh
uv run python examples/sentiment_demo.py
uv run python examples/sentiment_demo.py --text "Great service" --text "Terrible product"
```

It prints a JSON array and stores feedback only in memory. Use the unified CLI
to train, save/load, and evaluate the learned predictor; see the root README.
Future domain applications are documented in the roadmap, not empty demo files.
Passing tests or classifying these examples does not establish real-world accuracy.
