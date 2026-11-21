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
Notification delivery and recurring scheduling require external wiring.

## Data removal

`docker compose down --volumes` removes this deployment's persistent data.
Use it only for a disposable exercise or after retaining required backups.
