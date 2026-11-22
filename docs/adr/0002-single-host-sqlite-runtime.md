# ADR 0002 · Use a single-host SQLite runtime

- Status: Accepted for the local reference.
- Documented: 22 November 2026.

## Context

Learners need to observe persistent jobs, ownership, retries, approval, and review
creation without first operating a broker and separate database service. The
reference runs an API and worker as separate processes on one host.

## Decision

Use SQLite for workflow state, proposals, decisions, and review records. Use
transactions for claims and for review creation together with job completion.
Use expiring leases and ownership tokens to reject stale workers. Apply schema
changes through ordered, checksummed migrations.

Telemetry and notification delivery use separate SQLite files. Compose mounts
persistent files in a volume shared by the relevant services.

## Consequences

The complete local lifecycle is reproducible with few dependencies. Transactional
review creation avoids a gap between the saved result and completed job state.
A single-host database also has write contention and availability limits. Local
load measurements establish neither multi-host capacity nor a service SLA.

This is not a distributed queue or a transaction spanning an external business
API. Backup, restore, schema compatibility, and reconciliation still matter.

## Alternative

A server database and broker could support different scaling and operational
requirements. They would introduce additional services, delivery semantics, and
configuration into the first learning environment. Revisit this decision when a
concrete deployment requires distributed capacity or availability.

## Evidence

- [Workflow store](../../production/store.py)
- [Migrations](../../production/01_workflow_runtime/migrations/)
- [Migration runner](../../production/category_05_deployment_and_operations/migrate.py)
- [Deployment and operations](../../production/category_05_deployment_and_operations/README.md)
