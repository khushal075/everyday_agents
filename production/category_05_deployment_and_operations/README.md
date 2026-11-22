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
| `check_alerts.py` | Evaluate alerts and optionally deliver them to a configured webhook. |
| `notifications.py` | Persist webhook delivery IDs, payloads, and bounded retry attempts. |
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

## Select the integrated policy workflow

The default API stamps new jobs with `sentiment`. To submit new policy-routing
jobs, add the following settings to the environment file:

```dotenv
FEEDBACK_WORKFLOW_MODE=policy
FEEDBACK_ROUTING_GENERATOR=fixture
```

Use the upgrade steps in the runbook before changing an existing deployment.
Migration 006 preserves existing jobs and reviews. Then recreate API and worker:

```bash
docker compose up -d --force-recreate --wait --wait-timeout 90 api worker
docker compose run --rm --no-deps smoke
```

The explicit fixture generator performs no inference. The smoke test submits
negative duplicate-charge feedback, approves its exact proposal, and verifies
the persistent route and citation. Existing jobs keep their saved workflow mode.

For actual Ollama inference, configure the worker instead:

```dotenv
FEEDBACK_ROUTING_GENERATOR=ollama
FEEDBACK_ROUTING_MODEL=qwen
FEEDBACK_OLLAMA_URL=http://host.docker.internal:11434/api/generate
FEEDBACK_MODEL_TIMEOUT=10
```

Use an exact installed model name. `host.docker.internal` addresses the host on
Docker Desktop; Linux hosts need a reachable inference service address or explicit
host-gateway configuration. The endpoint is operator configuration and must be
trusted with feedback data. No model is downloaded or model server started by
Compose. Cold-start latency can exceed the bounded socket timeout.

Missing model configuration fails explicitly. Already saved proposals resume
without inference. Read [Category 02](../category_02_models_retrieval_and_tools/README.md)
for the complete lifecycle, failure behavior, and model-quality limits.

## Portable identity-provider authentication

The API also accepts OIDC bearer access tokens. Configure these settings in the
local environment file, then recreate the API container:

```dotenv
FEEDBACK_OIDC_ISSUER=https://your-issuer.example/realm
FEEDBACK_OIDC_AUDIENCE=your-feedback-api
FEEDBACK_OIDC_JWKS_URL=https://your-issuer.example/realm/jwks
FEEDBACK_OIDC_TENANT_CLAIM=tenant_id
FEEDBACK_OIDC_PERMISSIONS_CLAIM=scope
FEEDBACK_CREDENTIALS='{}'
```

Use the exact issuer and JWKS URL published by your provider. The audience
identifies this API and may differ from the login application's client ID.
The provider must issue RS256-signed access tokens with `iss`, `aud`, `sub`,
`exp`, `iat`, and a nonempty tenant claim.

The tenant claim must be assigned by trusted provider policy. Users must not be
able to edit their own tenant membership. Configure top-level permission claims
as either space-separated scopes or a string list. Supported permissions are
`submit_feedback`, `read_job`, `approve_action`, and `cancel_job`.
Provider-specific nested roles need a claim mapper to this top-level format.

```bash
docker compose up -d --force-recreate api
```

Supply `Authorization: Bearer ...` on HTTP requests. API-key callers continue
to work when configured. A request must supply one credential. Setting
`FEEDBACK_CREDENTIALS` to an empty object disables API-key identities.

For a bearer-authenticated deployment smoke test, set `FEEDBACK_BEARER_TOKEN`
in the environment file and leave `FEEDBACK_API_KEY` empty. The token needs
all submission, read, and approval permissions. Acquire it using your provider's
supported login or OAuth flow.

```bash
docker compose run --rm --no-deps smoke
```

Signature algorithm, issuer, API audience, expiry, issue time, and subject are
verified before tenant access. Signing keys are cached. A key-fetch outage with
no usable cached key returns 503. Invalid tokens return 401 and insufficient
permissions return 403.

## Deliver alerts to a webhook

Configure the destination and optional receiver credential:

```dotenv
FEEDBACK_ALERT_WEBHOOK_URL=https://your-receiver.example/alerts
FEEDBACK_ALERT_WEBHOOK_TOKEN=your-receiver-token
```

Delivery is explicitly enabled by `--notify`:

```bash
docker compose run --rm --no-deps ops python -m production.category_05_deployment_and_operations.check_alerts --notify
```

The receiver gets JSON containing `delivery_id`, `created_at`, and `alerts`.
The delivery ID is also sent in `Idempotency-Key` and `X-Delivery-ID` headers.
An optional bearer credential authenticates the webhook request. Redirects are
refused, and HTTPS is required for remote destinations.

Each delivery reserves at most three attempts, including attempts across process
restarts. HTTP 429, 5xx responses, and network failures are retried. Other 4xx
responses fail immediately. Each HTTP request has a five-second timeout.
Delivery metadata is saved in `/data/notifications.sqlite3` on the runtime volume.

Use `--delivery-id` to repeat a known delivery with the same destination and
alert payload. A delivery already confirmed as sent causes no new request:

```bash
docker compose run --rm --no-deps ops python -m production.category_05_deployment_and_operations.check_alerts --notify --delivery-id incident-123
```

New invocations without an explicit ID create new deliveries. This provides no
automatic incident grouping or alert suppression. If a request reaches the
receiver but its response is lost, a retry can arrive with the same ID. The
receiver must enforce idempotency. A crash after the final request but before
confirmation needs reconciliation using the receiver's records.

Alerts still return exit code 1 after successful delivery. Evaluation or delivery
failure returns 2. A clear result sends no notification. Repeating a delivery ID
with changed alert details is rejected.

## Verify the portable integrations locally

```bash
uv run python -m unittest tests.integration.test_external_integrations -v
```

The tests use an actual loopback JWKS server, ephemeral RSA keys, a real HTTP
webhook receiver, and an API/worker process smoke test. They cover invalid
signatures and claims, tenant isolation, permission denial, provider outage,
retry identity, connection drops, redirect refusal, and persisted retry limits.

The tests enable HTTP only for explicit loopback fixtures. Remote provider and
receiver configuration still requires HTTPS. These checks exercise portable
protocol adapters with local fixtures. A particular hosted provider and
notification endpoint need live credentials and a separate verification run.

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
worker, and approval flow. CI is configured to run those checks on each push and pull request for both
sentiment and policy workflows; policy CI uses the explicit fixture generator.

Verification combines the 21 November operations checks with the full-suite and
both-workflow container checks on 22 November 2026, using Docker Desktop engine
29.7.2 on Apple Silicon:

| Check | Result |
| --- | --- |
| Full Python suite | 153 tests passed, including policy integration, operations, and portable integration checks. |
| Locked container build | Passed; the runtime uses UID 10001. |
| Compose startup and service health | Passed. |
| Authenticated submission, approval, and completion | Passed through the actual container API. |
| API and worker restart persistence | Saved approval request survived both restarts and completed afterward. |
| SQLite backup and restore | Integrity and foreign-key checks passed; smoke passed after restore. |
| Alert outcomes | Clear returned 0, an injected old job returned 1, and missing data returned 2. |
| Environment-file parsing | Credential mapping and tools profile validated. |
| Portable OIDC | Loopback JWKS verification and a bearer-authenticated API/worker process smoke test passed. |
| JSON webhook | Local receiver delivery, ambiguous connection retry, redirect refusal, and persistent retry limits passed. |

The GitHub Actions workflow is added for future pushes. These local results
verify its component commands; a hosted workflow run will provide CI evidence.

The deployment uses one host and SQLite storage. Health checks show
responsiveness and recent worker progress. Docker reports unhealthy services,
and the restart policy restarts exited processes. An unhealthy but running
process needs operator or orchestrator intervention.

Provider-specific login, TLS termination, remote endpoint verification,
distributed database failover, and multi-host orchestration remain deployment
integration work. The worker supports the existing sentiment baseline and the
integrated policy workflow. Policy review creation is transactional SQLite execution.
Ollama protocol behavior was verified with local HTTP fixtures; no live model server
was available during this run. External business-tool APIs need separate adapters.
