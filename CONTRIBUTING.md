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

## Repository tracks

- `examples/concepts/`: 15 implemented standalone concept lessons.
- `src/everyday_agents/`: implemented reusable code and sentiment reference app.
- `production/`: implemented Phase 2 reference system and five categories of operational labs.

Implement lessons progressively with clear objectives and failure cases. Add
meaningful checks in the appropriate unit or integration test area and keep full
unittest discovery working. Do not
pre-create empty source/configuration/schema placeholders. Record future scope
in the roadmap, and update coverage status only with actual test evidence.
Preserve the historical v0.1.0 tag while developing subsequent work.

## Writing learning material

Connect each lesson to a question readers can recognize. Include the objective,
prerequisites, command, expected behavior, one change to try, and a checkpoint
question. Link to the responsible files so readers can move from behavior to code.
Distinguish deterministic fixtures, real inference, local execution, and external
integrations. Keep commands reproducible from their stated working directory.

Use [the learning path](docs/learning-path.md) to place new material. Walkthroughs
explain behavior; [ADRs](docs/adr/README.md) explain significant design trade-offs.
Update documentation alongside changes that affect the observed behavior.
