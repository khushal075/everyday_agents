# Learning path

## Current status

The sentiment-focused `v0.1.0` reference application is implemented and preserved.
Phase 1 contains 15 concept exercises. Phase 2 contains the five-category
reference implementation, including the integrated policy-routing workflow.
Start with the [runnable concepts guide](../examples/concepts/README.md) or the
[production guide](../production/README.md).

## Phase 1: understand the concepts

The standalone scripts under `examples/concepts/` build the following ideas progressively.
Use their README for exact file names, commands, and expected results.

| Unit | Concept example | Main topics |
| --- | --- | --- |
| 01 | Rule-based agent | Goal, observation, state, action, stopping |
| 02 | ML-powered agent | Training vs inference, learned action selection |
| 03 | Tools and decision policies | Structured arguments, registry, action selection |
| 04 | Authorization and approval boundaries | Permissions, approval, untrusted data |
| 05 | Verified feedback loop | Observe effects, verify, bound execution, stop on failure |
| 06 | Retrieval | Keyword overlap, passages, source references |
| 07 | Grounded RAG | Retrieve context, generate an answer, cite evidence |
| 08 | Reranked RAG | Reorder keyword ties using word order; select model context |
| 09 | Memory and context | Remember a topic and resolve a simple follow-up |
| 10 | Planning and replanning | Search a simulated map; replan after a blocked move |
| 11 | Safe recovery | Timeouts, retries, idempotency, ambiguous outcomes |
| 12 | Checkpoints and resumable approval | Save state, restart, resume a specific approved action |
| 13 | Coordinated agents | Delegation, parallel work, handoffs, bounded responsibilities |
| 14 | Protocol integration | Real MCP tool discovery/calls; communication boundaries |
| 15 | Evaluation and observability | Structured traces, fixed expectations, elapsed time, regression detection |

Not every example needs an LLM, a database, or a framework. Real LLM/protocol
examples must declare their dependencies and credentials. Simulated responses
can support deterministic tests, but must be labelled as simulated. Protocol
integration may need a small companion process rather than a single file.

Trace history is not active memory unless the agent uses it. Retrieving documents
is not RAG unless generation uses the retrieved context. A model proposing an
action and a policy authorizing it are separate responsibilities.

## Phase 2: demonstrate production behaviour

Follow the five categories under `production/` for saved jobs, models/retrieval/tools,
reliability/access, evaluation/observability, and deployment/operations. The
reference application reuses the sentiment package and adds a policy mode with
persistent evidence, approval, resume, and review verification.

Run the complete local exercise from the repository root:

```bash
uv run python -m production.category_02_models_retrieval_and_tools.integrated_feedback
```

It uses an explicitly labelled fixture generator and separate worker processes.
Select Ollama for real inference as documented in Category 02. Use Category 05
for actual HTTP container deployment and operations. Representative quality
benchmarks, external business APIs, and multi-host infrastructure are extensions,
not capabilities established by these local examples.

## Where the existing implementation fits

The existing sentiment example is the structured reference application. Its
`core`, `ml`, training, CLI, dataset, and tests remain usable without following
the new lessons. The historical `v0.1.0` tag is not moved or replaced.

Check the [coverage matrix](coverage-matrix.md) before describing a concept or
production property as implemented. Planned future use cases are listed in the
[roadmap](roadmap.md), rather than represented by empty source packages.
