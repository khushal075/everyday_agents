# Getting started

Install uv and Python 3.12 or newer. From the repository root run `uv sync --locked`.
The package and dependencies are installed into `.venv`; no activation is needed.

```sh
uv run everyday-agents sentiment run --text "This is terrible"
uv run everyday-agents sentiment train --data data/samples/sentiment/feedback.jsonl --output artifacts/models/sentiment-v1
uv run everyday-agents sentiment run --model artifacts/models/sentiment-v1 --text "Helpful service"
```

The first command uses the deterministic lexicon. The second trains TF-IDF and
logistic regression, reports validation results, and saves an artifact. The third
loads that artifact and runs the complete agent without training.

Use a new artifact output folder for each model version; existing destinations are
refused. Recreate the training environment with the same Python major/minor and
`uv.lock` before loading a model. Load only trusted local joblib files.

Commands work through `uv run python -m everyday_agents` as well. For subcommand
options use `uv run everyday-agents sentiment --help`. `--version` reports the
installed package version. Examples and sample datasets live in the source
checkout; wheel users must supply their own labelled dataset paths.

All successful unified commands print one JSON object. Errors use stderr and a
nonzero exit status. Results are not persisted unless training writes an artifact;
feedback records stay in memory. The sample model is for demonstration only.

Run the complete test suite with:

```sh
uv run --locked python -m unittest discover -s tests -v
```

On a cross-filesystem uv cache warning, use `UV_LINK_MODE=copy uv sync --locked`
(or the corresponding environment setting on your shell). This changes how files
are installed, not model behaviour.
