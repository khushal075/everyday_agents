# 05 · Deployment and operations

Run the feedback workflow as a containerized API and persistent worker. Apply
versioned migrations, check service health, exercise approval through HTTP,
and evaluate local alert rules.

## Files

| File | Responsibility |
| --- | --- |
| `Dockerfile` | Build a shared non-root runtime with locked Python dependencies. |
| `Dockerfile.dockerignore` | Limit build inputs and exclude local secrets and runtime databases. |
| `compose.yaml` | Run migration, API, worker, smoke, and operations services. |
| `.env.example` | Describe local credential, image, and port configuration. |
| `migrate.py` | Apply pending migrations, record checksums, and adopt verified manual schemas. |
| `run_worker.py` | Poll for jobs, publish heartbeats, and handle graceful shutdown. |
| `healthcheck.py` | Check API responsiveness, database readability, and worker heartbeat/PID. |
| `alerts.json` | Configure alert thresholds and the observation window. |
| `check_alerts.py` | Print state and telemetry alerts with distinct clear/alert/error exit codes. |
| `smoke_test.py` | Submit, approve, and verify a job through the running HTTP API. |
| `runbook.md` | Describe backup, restore, upgrades, rollback, and recovery. |

The CI workflow is `.github/workflows/production-checks.yml`.

## Configure

Run from the repository root with Docker Compose available.

```bash
cp production/category_05_deployment_and_operations/.env.example production/category_05_deployment_and_operations/.env
```

Generate the credential and write the local environment file. This overwrites
the copied template, so use it for initial setup.

```bash
uv run python - <<'PY'
import json
import secrets
from pathlib import Path

key = secrets.token_urlsafe(32)
credentials = {key: {
    "subject_id": "local-operator",
    "tenant_id": "local",
    "permissions": ["submit_feedback", "read_job", "approve_action", "cancel_job"],
}}
path = Path("production/category_05_deployment_and_operations/.env")
path.write_text(
    f"FEEDBACK_API_KEY={key}\n"
    + "FEEDBACK_CREDENTIALS='" + json.dumps(credentials) + "'\n"
    + "FEEDBACK_PORT=8000\n"
    + "EVERYDAY_AGENTS_IMAGE=everyday-agents:local\n"
)
path.chmod(0o600)
PY

export COMPOSE_FILE=production/category_05_deployment_and_operations/compose.yaml
export COMPOSE_ENV_FILES=production/category_05_deployment_and_operations/.env
```

Change `FEEDBACK_PORT` if another server uses port 8000. Docker exposes this API
on the host loopback address. The environment file is ignored by Git and
excluded from the image build context.

## Build and start

```bash
docker compose build
docker compose up -d --wait --wait-timeout 90 api worker
docker compose ps -a
```

A one-shot migration service must finish successfully before API and worker
startup. Each migration's schema changes and history record commit together.
The API and worker use `/data/feedback.sqlite3` and
`/data/telemetry.sqlite3` in a named volume. The image runs as UID 10001.

## Verify the deployed workflow

```bash
docker compose run --rm --no-deps smoke
docker compose exec -T api python -m production.category_05_deployment_and_operations.healthcheck api
docker compose exec -T worker python -m production.category_05_deployment_and_operations.healthcheck worker
docker compose run --rm --no-deps ops python -m production.category_04_evaluation_and_observability.metrics --database /data/telemetry.sqlite3
docker compose run --rm --no-deps ops
```

The smoke test submits negative feedback, waits for an immutable proposal,
approves it, and verifies completion by the worker. It creates one real local
review item in the deployment database.

The operations command evaluates recent failure rates and API p95 latency,
old eligible queued jobs, expired worker leases, and old approval requests.
Alert findings are printed as JSON. Integrate this command with a scheduler
and notification destination when those are available.

| Command | Exit codes |
| --- | --- |
| Health check | 0 healthy, 1 unhealthy |
| Smoke test | 0 passed, 1 failed |
| Alert check | 0 clear, 1 active alerts, 2 unable to evaluate |
| Migration | 0 applied/already applied, 1 failed |

## Stop and restart

```bash
docker compose stop
docker compose start api worker
```

Stopping retains database files. SIGTERM asks the worker to finish its current
attempt and remove its heartbeat. Compose allows 45 seconds before forced
shutdown. Heartbeat checks reject stale timestamps and missing worker processes.

```bash
docker compose down
```

This removes containers and the network while retaining the named data volume.
See the runbook before removing volumes.

## Local Python commands

The same modules run outside containers:

```bash
uv sync --locked
uv run python -m production.category_05_deployment_and_operations.migrate --database feedback-runtime.sqlite3 --adopt-existing
FEEDBACK_DB_PATH=feedback-runtime.sqlite3 uv run python -m production.category_05_deployment_and_operations.run_worker
```

Use `--adopt-existing` only for a database created by the earlier manual
migration commands. The runner compares its schema against a migration-built
reference before recording its existing versions. A new database needs no
adoption flag. Stop services before running migrations.

## Verification and boundaries

Local operations tests cover fresh/repeated migrations, manual adoption,
rollback on migration failure, checksum mismatch, health failures, and alerts.
The deployment exercise builds the image and checks the actual container API,
worker, and approval flow. CI runs those checks on each push and pull request.

Verified locally on 21 November 2026 using Docker Desktop engine 29.7.2 on
Apple Silicon:

| Check | Result |
| --- | --- |
| Full Python suite | 120 tests passed, including six operations regression tests. |
| Locked container build | Passed; the runtime uses UID 10001. |
| Compose startup and service health | Passed. |
| Authenticated submission, approval, and completion | Passed through the actual container API. |
| API and worker restart persistence | Saved approval request survived both restarts and completed afterward. |
| SQLite backup and restore | Integrity and foreign-key checks passed; smoke passed after restore. |
| Alert outcomes | Clear returned 0, an injected old job returned 1, and missing data returned 2. |
| Environment-file parsing | Credential mapping and tools profile validated. |

The GitHub Actions workflow is added for future pushes. These local results
verify its component commands; a hosted workflow run will provide CI evidence.

The deployment uses one host and SQLite storage. Health checks show
responsiveness and recent worker progress. Docker reports unhealthy services,
and the restart policy restarts exited processes. An unhealthy but running
process needs operator or orchestrator intervention.

External identity providers, TLS termination, remote notification delivery,
distributed database failover, and multi-host orchestration remain deployment
integration work. Model inference and review creation still use the existing
local sentiment baseline and SQLite workflow.
