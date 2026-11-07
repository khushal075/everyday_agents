# Concept and production coverage

Status meanings:

- **Local**: implemented in the existing reference application with local tests.
- **Planned**: teaching example or production exercise not implemented.
- Local software tests do not prove real-world model quality or service reliability.

Every Phase 1 standalone concept example is currently **planned**. References to
unit numbers below describe the learning path, not existing executable files.
Every Phase 2 production exercise is also currently **planned**.

| Area | Existing v0.1 evidence and limits | Phase 1 units | Phase 2 proof still needed |
| --- | --- | --- | --- |
| Goal, loop, stopping | Local: one-cycle Agent, success/failure handling | 01, 05 | Long-running completion/cancellation behaviour |
| Models and decisions | Local: lexicon baseline, TF-IDF/logistic regression, training/inference | 02, 10 | Representative data, calibration, model-change evaluations |
| Decision policy | Local: sentiment label selects record/review | 03 | Versioned policies and integration-level behaviour |
| Authorization and security | Local: feedback tool rejects unsupported actions/parameters; no identity/access system | 04, 07 | Authentication, least privilege, tenant isolation, injection exercises |
| Tool execution and verification | Local: in-memory records verified against stored fields | 03, 05 | Real side effects, ambiguous results, independent verification |
| Retrieval, RAG, reranking | Not implemented | 06–08 | Source permissions, quality, freshness, real retrieval/generation |
| State, memory, context | Local: transient records only; no active memory retrieval | 09 | Durable/scoped stores, retention, context and privacy controls |
| Planning and adaptation | Not implemented | 10 | Replanning under real changes, bounded autonomy |
| Orchestration and coordination | Local: sequential single-cycle workflow only | 13 | Concurrent tasks, delegation boundaries, cancellation |
| Reliability and recovery | Local: exceptions propagate; no retries or execution checkpoints | 11, 12 | Restart recovery, idempotency, duplicate deliveries, partial failures |
| Human approval | Not implemented; pending_review is a status, not an approval workflow | 04, 12 | Persisted approvals bound to current action and parameters |
| Evaluation | Local: classifier metrics, baseline comparison, explicit final test option | 08, 15 | Independent task benchmarks and rollout regression gates |
| Observability and budgets | Local: returned AgentRun and CLI JSON; no telemetry or cost accounting | 05, 15 | Correlated traces, alerts, latency/cost/step budgets |
| Interfaces and protocols | Local: CLI and Python API; no MCP/A2A server | 14 | Real protocol interoperability, authorization and disconnects |
| Deployment and operations | Local: wheel/sdist and fresh-install smoke check; CI configured | Cross-cutting setup | Deployed services, queues/workers, runtime configuration and rollback |

## Evidence for future changes

For an implemented example or operational exercise, add the source path, test
path, reproducible command, dependencies, observed result, and remaining gap.
Distinguish local fixtures from real integrations. If a capability is not tested,
leave it planned or explicitly mark its evidence as incomplete.
