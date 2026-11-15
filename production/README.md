# Phase 2: production behaviour and infrastructure

The [workflow runtime exercise](01_workflow_runtime/README.md) runs locally
with a feedback API, a separate worker, and a shared SQLite database. The
remaining operational exercises are planned.

The working v0.1 sentiment application remains under
`src/everyday_agents/agents/sentiment/`. Its local tests and packaging checks do
not establish distributed reliability, production model quality, or deployment
readiness.

## Planned scope

After the Phase 1 concepts are understood, build one integrated reference system
and demonstrate its operational behaviour with real processes and integrations:

- Persistent state, checkpoints, restarts, and recovery after partial execution.
- Concurrent workers, stable operation IDs, and duplicate-side-effect prevention.
- Durable approval tied to the exact proposed action and its parameters.
- Authentication, tenant isolation, scoped data access, and tool permissions.
- Real retrieval/model/tool integrations, with untrusted-content boundaries.
- Timeouts, retries, cancellation, execution/cost limits, and escalation.
- Traces, task evaluations, monitoring, and configuration/model versioning.
- Reproducible deployment and documented failure/recovery exercises.

Create application, deployment, infrastructure, and scenario files when their
first implementation is ready. Reuse or extend `src/everyday_agents/` for shared
Python functionality; avoid duplicating its implementation in this directory.

## Evidence required

For each behaviour, record the environment, exact run command, injected failure,
expected result, observed result, and remaining limitations. A simulated service
is not a tested external integration. Do not describe an exercise as verified
until it has actually run.

Track those boundaries in the [coverage matrix](../docs/coverage-matrix.md).
