# Concept and production coverage

**Implemented locally** means code and reproducible checks exist. It does not
establish real-world model accuracy, an availability SLA, or support for every
agent architecture. Phase 1 has 15 concept examples; Phase 2 has five implemented
categories and an integrated policy-routing application.

| Area | Phase 1 example | Phase 2 evidence | Remaining boundary |
| --- | --- | --- | --- |
| Goal, observation, action, stopping | 01, 05 | Saved job states, worker completion, cancellation | Domain-specific success criteria |
| Models and decisions | 02, 10 | Sentiment baseline; optional Ollama routing adapter; trained-model batching benchmark | Representative quality, calibration, rollout evaluation |
| Policy and tool arguments | 03 | Route validation, permitted source/heading mapping, immutable proposal | Policy lifecycle and domain semantics |
| Authentication and authorization | 04 | API keys, optional OIDC, tenant-scoped access and worker permissions | Hosted provider validation and tenant-specific source access |
| Tool execution and verification | 03, 05 | Transactional persistent review tool with route/citation read-back | External business API idempotency and reconciliation |
| Retrieval and RAG | 06, 07 | Keyword policy retrieval, bounded evidence, model context and citation validation | Paraphrases, retrieval quality, source freshness |
| Reranking | 08 | The production reference uses keyword ranking | Semantic rerankers and representative evaluation |
| State, memory, context | 09 | Durable jobs, immutable evidence snapshots, resumed proposal restoration | Conversational memory service, retention policy |
| Planning and adaptation | 10 | A bounded feedback-routing workflow | Open-ended autonomous planning is outside this reference |
| Coordination | 13 | Concurrent component checks and HTTP load exercise | Distributed multi-agent orchestration |
| Reliability and recovery | 11, 12 | Expiring leases, stale-owner rejection, capped retries, real crash/restart checks | Cross-service transactions and external ambiguous outcomes |
| Human approval | 04, 12 | Immutable exact-action proposals, durable decisions, restart-safe execution | Organizational approval UX and business governance |
| Evaluation | 08, 15 | Fixed-case checks, classification metrics, failure-path integration tests | Independent representative task-quality benchmarks |
| Observability | 05, 15 | Correlated component events, SQLite aggregation, load and batching measurements, alerts | Hosted telemetry, dashboards, hard cost budgets |
| Interfaces and protocols | 14 | Authenticated HTTP API; local JWKS and webhook protocol tests | A2A is not implemented; hosted protocol validation varies |
| Deployment and operations | Setup | Locked non-root image, tracked migrations, Compose health/smoke, backup/restore runbook, CI configuration | TLS, multi-host orchestration, hosted CI evidence after push |

## Reproduce the evidence

From the repository root:

```bash
uv sync --locked
uv run python -m unittest discover -s tests -q
uv run python -m production.category_02_models_retrieval_and_tools.integrated_feedback
uv run python -m production.01_workflow_runtime.restart_and_resume
uv run python -m production.category_03_reliability_and_access.crash_and_retry
```

The full suite passed 153 tests on 22 November 2026. Policy-specific tests in
`tests/integration/test_feedback_workflow.py` verify exact proposal reuse,
approval/rejection, tenant isolation, permissions, cancellation, stale leases,
process crashes, bounded retries, model validation, and verification failures.
Actual HTTP inference fixtures check the adapter and worker together. They do
not establish the quality of an installed model.

See [the concepts guide](../examples/concepts/README.md) for individual scripts
and [Category 05](../production/category_05_deployment_and_operations/README.md)
for deployment commands and the dated verification table. Both workflow modes
passed isolated container startup, health, smoke, restart, and clear-alert checks.
No live Ollama server was available during this verification.

Future claims should identify source paths, checks, reproducible commands,
observed results, and remaining limits. Keep fixture evidence distinct from
live hosted integrations and representative model-quality measurements.
