# Contributing

Use Python 3.12+ and uv. Install with `uv sync --locked` and run all tests with:

```sh
uv run --locked python -m unittest discover -s tests -v
```

Use `uv add` for dependencies and commit pyproject.toml and uv.lock together.
Keep .venv, private/raw datasets, generated model artifacts, and credentials out
of Git. Synthetic sample data should document its origin and limitations.

Preserve the separation between core orchestration, shared ML utilities, and
domain implementations. Add tests for meaningful success/failure boundaries.
Do not claim model quality from passing software tests or synthetic demo scores.

Before a release, run tests, `uv build`, and the clean-wheel smoke check used in
`.github/workflows/ci.yml`. Use small, coherent commits. Create an annotated local
version tag on the final verified commit; publishing and pushing are separate.
