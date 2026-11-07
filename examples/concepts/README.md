# Phase 1: agent concepts

This directory is reserved for small, standalone learning examples. No concept
examples have been implemented yet. The working sentiment application remains
in `src/everyday_agents/agents/sentiment/`; its runnable demo remains at
`examples/sentiment_demo.py`.

See the [learning path](../../docs/learning-path.md) for the proposed sequence and
the [coverage matrix](../../docs/coverage-matrix.md) for implementation status.
Examples will be added individually after their scope is agreed.

## Example contract

Each future example should have:

- One concrete objective and clearly named agent components.
- A complete, independently runnable flow with stated dependencies.
- Expected output and one meaningful failure demonstration.
- A distinction between model decisions and authorization rules.
- Explicit completion conditions and execution limits.
- A description of implemented, simulated, and omitted behaviour.
- Checks under `tests/concepts/` when executable examples are introduced.

Some protocol examples may require a small companion process. Explain that
requirement rather than representing a local function call as a real protocol.
The learning examples should not require navigating the reusable package to
understand their basic behaviour. Any intentional repetition serves readability.
