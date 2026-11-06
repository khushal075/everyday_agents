# Examples

Only sentiment is implemented in v0.1. Other demo files are placeholders.

From the repository root after `uv sync --locked`:

```sh
uv run python examples/sentiment_demo.py
uv run python examples/sentiment_demo.py --text "Great service" --text "Terrible product"
```

This rules-based demo prints a JSON array and stores feedback only in memory.
Use the unified CLI to train a model, save/load it, and evaluate independent data;
see the root README. Passing software tests or classifying these examples does
not establish real-world sentiment accuracy.
