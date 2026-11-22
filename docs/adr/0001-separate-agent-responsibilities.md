# ADR 0001 · Separate agent responsibilities

- Status: Accepted for the local reference.
- Documented: 22 November 2026.

## Context

A sentiment prediction can come from a rules baseline or a learned classifier.
Changing that predictor should not require rewriting action execution. A reported
tool success also needs a separate check against what actually happened.

## Decision

The core defines Predictor, Policy, and Tool contracts. `Agent.run` coordinates
predict → decide → execute → verify. Domain prediction types remain domain-owned;
`Decision`, `ActionResult`, and `AgentRun` describe the shared boundaries.

The production worker retains these responsibilities while coordinating leases,
approval, and transactions itself. The core one-cycle Agent does not own durable
workflow recovery.

## Consequences

Components can be replaced and checked independently. Prediction does not grant
execution permission, and execution does not establish model accuracy. The cost
is more interfaces and files than a single-function demonstration, which is why
standalone concept lessons introduce the responsibilities first.

The baseline remains deterministic. Using these contracts alone does not make
an implementation ML-powered.

## Alternative

One function could predict, select an action, and write its result. It reduces
initial code, but couples model changes to execution and makes verification
boundaries harder to explain and check.

## Evidence

- [Core contracts and Agent](../../src/everyday_agents/core/agent.py)
- [Core records](../../src/everyday_agents/core/schemas.py)
- [Sentiment assembly](../../src/everyday_agents/agents/sentiment/agent.py)
- [Production worker](../../production/worker.py)
