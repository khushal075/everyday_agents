# Concept example checks

Reserved for checks of the Phase 1 examples. No concept tests or examples are
implemented yet. The package marker permits normal recursive unittest discovery
when the first test is added.

Future checks should run the standalone example or exercise an actual failure
boundary. Use local fixtures for repeatability, explicitly identify simulated
model/tool responses, and keep real-service checks opt-in with stated setup.
Do not claim that mocked behaviour verifies a real service integration.

The existing core, ML, sentiment, CLI, and artifact checks remain in `tests/unit/`
and `tests/integration/` and run through the existing full-suite command.
