# Phase 2 · Production behavior and infrastructure

Follow one feedback application from HTTP submission to a verified outcome.
The API persists jobs in SQLite. A separate worker predicts sentiment, chooses
an action, enforces permissions and approval, and commits the result.

## Learning sequence

| Category | Run and observe |
| --- | --- |
| [01 · Workflow runtime](01_workflow_runtime/README.md) | Submit feedback with the worker offline and process the saved job later. |
| [02 · Models, retrieval, and tools](category_02_models_retrieval_and_tools/README.md) | Retrieve policy evidence, validate recommendations, and exercise scripted failures. |
| [03 · Reliability and access](category_03_reliability_and_access/README.md) | Recover expired leases, reject stale owners, bound retries, enforce tenant access, and persist approval or cancellation. |
| [04 · Evaluation and observability](category_04_evaluation_and_observability/README.md) | Trace actual component events, summarize metrics, and measure HTTP load and model inference. |
| [05 · Deployment and operations](category_05_deployment_and_operations/README.md) | Build containers, apply tracked migrations, check health, run an approval smoke test, and practice backup/restore. |

## Start with isolated exercises

From the repository root:

```bash
uv sync --locked
uv run python -m production.01_workflow_runtime.restart_and_resume
uv run python -m production.category_03_reliability_and_access.crash_and_retry
uv run python -m production.category_03_reliability_and_access.permissions_and_approval
```

Each exercise initializes a temporary workflow database. Category READMEs provide
the remaining commands, expected results, and injected failure descriptions.

For the persistent service, follow the
[Category 05 setup](category_05_deployment_and_operations/README.md). It configures
credentials, runs migrations before startup, and mounts persistent data.
Operational recovery commands are in the [runbook](category_05_deployment_and_operations/runbook.md).

## Implemented behavior

- Persistent jobs and transactional SQLite review creation.
- Expiring leases, current-owner tokens, bounded retries, and escalation reasons.
- Tenant-scoped API access and worker tool permissions.
- Immutable action proposals and durable approval decisions.
- Cancellation that revokes pending work and worker ownership.
- Structured component events, stage metrics, and distinct completed-job counts.
- Real local HTTP service-load measurements and model batching benchmarks.
- Tracked migrations, non-root Docker services, health checks, and CI configuration.
- Local alert evaluation and optional durable JSON webhook delivery.
- Optional OIDC bearer authentication using configured signing keys.

The production worker reuses the sentiment predictor and decision policy in
`src/everyday_agents/agents/sentiment/`. Category 02 demonstrates a separate
retrieval workflow with scripted model responses and an in-memory tool.

## Verification

The local suite passed 132 tests on 21 November 2026. Container checks covered
startup, API and worker health, authenticated approval and completion,
restart persistence, backup/restore, and alert outcomes.

OIDC and webhook integration tests use actual loopback HTTP fixtures. They
verify signed-token claims, tenant isolation, permission denial, provider
unavailability, idempotency headers, connection-drop retries, and persisted
attempt limits. A real-process smoke test also verifies bearer authentication.

## Remaining integration boundaries

The reference deployment uses a single host and SQLite. Real retrieval and
external model/tool execution still need to be connected to the persistent
worker. Hosted identity providers and notification destinations require live
configuration and verification.

Telemetry delivery is best effort. External webhook receivers enforce
idempotency for repeated delivery IDs. Escalation records a failed job and reason.
Recurring alert scheduling, remote notification formatting, dashboards, TLS
termination, and multi-host orchestration depend on the deployment environment.
