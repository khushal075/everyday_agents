# Feedback service operations

## Inspect service state

Set `COMPOSE_FILE` and `COMPOSE_ENV_FILES` as shown in the README.

```bash
docker compose ps -a
docker compose logs --tail 100 api worker migrate
docker compose run --rm --no-deps ops
```

Check whether a job is queued, running, awaiting approval, completed, or failed.
Approval waiting releases the worker lease. Cancellation and escalation use
the failed state with explicit flags or reasons.

## Migration and upgrade

1. Stop API and worker processes.
2. Back up the workflow database and copy the backup off the runtime volume.
3. Build the new image from the intended Git commit.
4. Run the migration service once.
5. Start API and worker and verify health.
6. Run the smoke test.

```bash
docker compose stop api worker
docker compose build
docker compose run --rm --no-deps migrate
docker compose up -d --wait --wait-timeout 90 api worker
docker compose run --rm --no-deps smoke
```

The runner verifies applied-file checksums and applies pending files in order.
A failed migration rolls back its schema and history entry. Fix the failure
and rerun. An applied migration is immutable. Add a new migration for subsequent
schema changes.

Earlier manual databases can be adopted after matching their schema to the
migration sequence. To import a host database, stop services and copy it into
the data volume as `/data/feedback.sqlite3`, preserving readable/writeable
ownership for UID 10001. Run the migration module with `--adopt-existing`.
Use a backup for the first import.

## Backup

Create a consistent SQLite snapshot using the backup API. This supports a
running source, although stopping writers gives a simpler recovery point.

```bash
docker compose run --rm --no-deps ops python -c 'import sqlite3; source=sqlite3.connect("/data/feedback.sqlite3"); target=sqlite3.connect("/data/feedback-backup.sqlite3"); source.backup(target); target.close(); source.close()'
mkdir -p backups
docker compose cp api:/data/feedback-backup.sqlite3 backups/feedback.sqlite3
```

The host destination should be a fresh backup location. Copy it to the storage
used for retained backups. The snapshot includes migration history, tenant
ownership, proposals, decisions, and review records.

Telemetry has its own database. Back it up separately when retained event history
is required. Workflow state remains the source of job outcomes.

## Restore

1. Stop API, worker, and any operations commands that open the workflow database.
2. Keep the current database as a recovery fallback.
3. Restore the chosen SQLite snapshot to `/data/feedback.sqlite3`.
4. Remove stale workflow journal/WAL files only after all database connections
   are closed and the replacement database is in place.
5. Ensure the file belongs to UID/GID 10001.
6. Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check`.
7. Run migration verification using the application version matching the backup.
8. Start services and run a smoke test.

A container-based restore can use the operations service with a read-only bind
mount containing the host backup:

```bash
docker compose stop api worker
docker compose run --rm --no-deps -v "$PWD/backups:/backup:ro" ops python -c 'import shutil; from pathlib import Path; source=Path("/backup/feedback.sqlite3"); target=Path("/data/feedback.sqlite3"); shutil.copyfile(source, target); [Path(str(target)+suffix).unlink(missing_ok=True) for suffix in ("-wal", "-shm", "-journal")]'
docker compose run --rm --no-deps ops python -c 'import sqlite3; db=sqlite3.connect("/data/feedback.sqlite3"); assert db.execute("PRAGMA integrity_check").fetchone()[0]=="ok"; assert not db.execute("PRAGMA foreign_key_check").fetchall(); db.close()'
```

The operations container runs as the same UID as the application. Restored
content therefore keeps application write access.

## Rollback

Retain the Git revision, image digest, and database snapshot for each release.
Rebuild or select the previous image and check its schema compatibility.

Schema migrations run forward. An older binary can reject newer migration
history or depend on earlier schema behavior. When compatibility is uncertain,
restore the matching pre-upgrade database snapshot together with the old image.
Restoring a snapshot returns job state to that recovery point and can require
reconciliation of work completed afterward.

## Worker recovery

A crashed worker leaves a running job until its lease expires. A new worker
reclaims eligible work using a new token. Stale tokens cannot save an outcome.
The default lease is 30 seconds. Three exhausted attempts escalate the job.

```bash
docker compose restart worker
docker compose exec -T worker python -m production.category_05_deployment_and_operations.healthcheck worker
```

A heartbeat can become stale during a blocked attempt. Investigate worker logs,
lease age, and the model or tool call before restarting. The heartbeat checker
runs inside the worker container so it can inspect the recorded PID.

## Approval and cancellation

Approve or reject the immutable proposal through the tenant-authenticated API.
A rejected decision is final for its operation ID. Changed action details
require a new proposal. Approval storage survives container restarts.

Cancel pending work through `POST /jobs/{job_id}/cancel`. Cancellation revokes
the worker claim and prevents subsequent local review creation. It cannot undo
a completed review or stop model computation already in progress.

## Alert handling

`check_alerts.py` reads the configured thresholds in `alerts.json`.
Job-age rules use current database state. Event rules use a rolling observation
window and require a minimum sample count.

- Old queued jobs suggest missing workers, contention, or insufficient capacity.
- Expired leases suggest crashed or blocked workers.
- Old approval requests need human attention.
- Elevated stage failure rates or API p95 latency need investigation.
- Exit code 2 means the checker could not evaluate the data and needs repair.

Authentication rejections are included in API failure rates. Consider expected
rejections when choosing thresholds. The local checker prints findings.
Use `check_alerts --notify` for the configured JSON webhook. Deliveries and
attempt counts persist in `/data/notifications.sqlite3`. Reuse a delivery ID
only with the same destination and payload. An ambiguous final attempt requires
checking receiver records before creating a new delivery. Back up the delivery
ledger when preserving notification history.

Recurring scheduling and provider-specific notification formatting require
external wiring.

## Data removal

`docker compose down --volumes` removes this deployment's persistent data.
Use it only for a disposable exercise or after retaining required backups.

## Identity-provider operations

The OIDC issuer, API audience, and JWKS endpoint are server configuration.
Validate a new provider with an authenticated smoke test before directing
users to it. API readiness checks verify the process and database; they do not
perform a provider login or signing-key availability probe.

Signing keys are cached for five minutes, with PyJWT's refresh controls for
unknown key IDs. Coordinate key rotation with the provider's supported overlap
period. Keep tenant and permission claim mapping under trusted administrative
control.

Do not log access tokens or place them in command-line arguments. Smoke-test
tokens are read from the environment. Expired tokens require a new provider
login or token grant. Changing issuer or audience requires recreating the API
container.

## Policy-workflow recovery

Migration 006 adds workflow mode and review metadata without rewriting existing
proposals or completed reviews. Existing jobs remain sentiment jobs. API mode
changes affect newly submitted jobs only, so a mixed queue is supported.

A policy job saves its complete recommendation and evidence before waiting for
approval. Resume restores that exact proposal, even when the model is unavailable
or the original policy document has changed. Recomputing it after approval would
change what was authorized. Submit a new job for a genuinely new proposal.

A timeout before proposal persistence can retry inference. A failure after the
proposal is saved reuses the saved proposal. Leases and cancellation are rechecked
before execution. Invalid output and disallowed routes escalate without a review.

Review insertion and job completion share a transaction. If post-commit verification
fails, the job stays completed and `worker.verification_failed` reports the problem.
Investigate the saved proposal and review; do not replay the business action merely
because its read-back failed. The worker returns nonzero for this verification failure.
