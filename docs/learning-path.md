# Learning path

## Current status

The sentiment-focused `v0.1.0` reference application is implemented and preserved.
Phase 1 concept examples and Phase 2 production exercises are planned. This
restructure adds their learning/documentation boundaries, not implementations.

## Phase 1: understand the concepts

Add small examples under `examples/concepts/` progressively. The proposed units
below describe teaching scope; no corresponding Python scripts exist yet.

| Unit | Concept example | Main topics |
| --- | --- | --- |
| 01 | Rule-based agent | Goal, observation, state, action, stopping |
| 02 | ML-powered agent | Training vs inference, learned action selection |
| 03 | Tools and decision policies | Structured arguments, registry, action selection |
| 04 | Authorization and approval boundaries | Permissions, approval, untrusted data |
| 05 | Verified feedback loop | Observe effects, verify, bound execution, stop on failure |
| 06 | Retrieval | Chunking, keyword/vector/hybrid search, filtering, sources |
| 07 | Grounded RAG | Retrieve context, generate an answer, cite evidence |
| 08 | Reranked RAG | Rank candidates, select context, compare retrieval quality |
| 09 | Memory and context | Use history, retrieve memory, manage context limits |
| 10 | Planning and replanning | LLM action proposals, decomposition, adapt plans |
| 11 | Safe recovery | Timeouts, retries, idempotency, ambiguous outcomes |
| 12 | Checkpoints and resumable approval | Save state, restart, resume a specific approved action |
| 13 | Coordinated agents | Delegation, parallel work, handoffs, bounded responsibilities |
| 14 | Protocol integration | Real MCP tool discovery/calls; communication boundaries |
| 15 | Evaluation and observability | Traces, task success, regression checks, cost/latency budgets |

Not every example needs an LLM, a database, or a framework. Real LLM/protocol
examples must declare their dependencies and credentials. Simulated responses
can support deterministic tests, but must be labelled as simulated. Protocol
integration may need a small companion process rather than a single file.

Trace history is not active memory unless the agent uses it. Retrieving documents
is not RAG unless generation uses the retrieved context. A model proposing an
action and a policy authorizing it are separate responsibilities.

## Phase 2: demonstrate production behaviour

Use `production/` for an integrated reference system, environment configuration,
and operational exercises. Shared Python code belongs in `src/everyday_agents/`.
Exercise real restarts, concurrency, external side effects, scoped access,
observability, and deployment. See the [Phase 2 scope](../production/README.md).

## Where the existing implementation fits

The existing sentiment example is the structured reference application. Its
`core`, `ml`, training, CLI, dataset, and tests remain usable without following
the new lessons. The historical `v0.1.0` tag is not moved or replaced.

Check the [coverage matrix](coverage-matrix.md) before describing a concept or
production property as implemented. Planned future use cases are listed in the
[roadmap](roadmap.md), rather than represented by empty source packages.
