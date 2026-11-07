# Adding an agent

1. Define domain input, prediction output, action names, and stopping conditions.
2. Implement predict(input_data) using the core Predictor contract. Start with a
   documented baseline; avoid forcing every domain into a score/label schema.
3. Implement decide(prediction) returning Decision with a reason.
4. Implement execute(input_data, decision) and verify(result). Validate actions
   and parameters, enforce necessary approval, and document side effects.
5. Assemble components using core Agent and add complete workflow tests.
6. For a learned model, implement Trainer.train(data), use shared data/splitting
   helpers where appropriate, and fit preprocessing on training data only.
7. Compare on independent data with domain-appropriate metrics. Reuse artifacts
   with a model-specific serializer and record compatibility requirements.

Sentiment is the working reference application. Future domains are listed in
`docs/roadmap.md`; create their directories when implementation starts.
Extend shared abstractions only for demonstrated requirements. Grouped photos,
user histories, and chronological tasks may need splitters beyond v0.1's random
row-level splitter. Planned agents must not silently trigger external actions.

For a Phase 1 teaching example, start in `examples/concepts/` with a self-contained
program and checks in `tests/concepts/`. Do not require readers to navigate the
shared runtime to understand the lesson. Explain which behaviours are simulated.
Phase 2 integrated systems may reuse the package and add operational exercises
under `production/`. Update the coverage matrix with actual evidence.
