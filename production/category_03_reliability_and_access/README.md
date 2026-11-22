# 03 · Reliability and access

The feedback workflow now demonstrates expiring worker leases, bounded retries,
tenant-scoped API access, durable approval, and cancellation.

## Files

| File | Responsibility |
| --- | --- |
| `recovery.py` | Choose retry delays and escalation after failed attempts. |
| `security.py` | Resolve configured credentials and check tenant scope and permissions. |
| `approvals.py` | Persist immutable action proposals and approval decisions. |
| `crash_and_retry.py` | Verify lease expiry, stale-token rejection, and recovery in a new process. |
| `permissions_and_approval.py` | Verify access, approval across restarts, cancellation, retry limits, and tool permissions. |

The shared API, store, and worker are in `production/`. Database changes are
kept in the existing workflow migration directory.

## Run the exercises

From the repository root:

```bash
uv sync --locked
uv run python -m production.category_03_reliability_and_access.crash_and_retry
uv run python -m production.category_03_reliability_and_access.permissions_and_approval
uv run python -m production.01_workflow_runtime.restart_and_resume
```

Each exercise creates a temporary database and applies the migrations.
The access exercise uses test-client HTTP calls and separate worker processes.

| Exercise | Verified behavior |
| --- | --- |
| Crash and retry | A process exits after claiming a job. Its lease expires, its token is rejected, and a fresh worker completes attempt 2 with one review. |
| Access and approval | Invalid credentials fail, cross-tenant lookups return 404, missing permissions return 403, and approval survives API and worker restarts. |
| Rejection and changed inputs | Rejection fails the job. Altering proposed parameters or execution inputs blocks review creation. |
| Cancellation | Cancelling queued, running, or waiting work prevents completion and approval. An old worker cannot reschedule or finish cancelled work. |
| Retry scheduling | Inference timeouts schedule retries after one and two seconds. The third failure escalates the job. The fixture advances retry timestamps after verifying the saved delays. |
| Tool permissions | A worker lacking the action permission creates no review. |

## Existing database

Stop the API and workers, back up the database, and apply only migrations
that have not already been applied, in numeric order:

1. `001_initial.sql`
2. `002_worker_leases.sql`
3. `003_retry_scheduling.sql`
4. `004_access_and_approvals.sql`
5. `005_cancellation_and_approval_controls.sql`
6. `006_policy_workflow.sql` — saved workflow mode and policy review metadata.

All files are under `production/01_workflow_runtime/migrations/`.
Migration 004 rebuilds the jobs table, preserves existing records, and assigns
existing jobs to tenant `local`. Existing jobs retain their automatic execution
behavior. New API submissions require approval before creating review items.

For a database already migrated through 003:

```bash
sqlite3 -bail feedback-runtime.sqlite3 < production/01_workflow_runtime/migrations/004_access_and_approvals.sql
sqlite3 -bail feedback-runtime.sqlite3 < production/01_workflow_runtime/migrations/005_cancellation_and_approval_controls.sql
sqlite3 -bail feedback-runtime.sqlite3 < production/01_workflow_runtime/migrations/006_policy_workflow.sql
sqlite3 feedback-runtime.sqlite3 'PRAGMA foreign_key_check;'
```

An empty foreign-key-check result means no violations were found.

## Configure caller identities

The API reads `FEEDBACK_CREDENTIALS`, a JSON mapping from API keys to
`subject_id`, `tenant_id`, and a list of `permissions`. Set it in the server
environment. With no credentials configured, protected requests return 401.

For a local exercise, generate a key and keep it available in the terminals
used for server startup and requests:

```bash
export FEEDBACK_API_KEY="$(uv run python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export FEEDBACK_CREDENTIALS="$(uv run python -c 'import json, os; print(json.dumps({os.environ["FEEDBACK_API_KEY"]: {"subject_id": "local-operator", "tenant_id": "local", "permissions": ["submit_feedback", "read_job", "approve_action", "cancel_job"]}}))')"
FEEDBACK_DB_PATH=feedback-runtime.sqlite3 uv run uvicorn production.api:app
```

This is an exercise credential resolver. Key rotation, TLS termination, and an
external identity provider require deployment configuration.

## Follow an approved job

Send `X-API-Key` with every request. Substitute the returned ID for
`YOUR_JOB_ID`. Run commands from a second terminal with the same API key.

```bash
curl -sS http://127.0.0.1:8000/feedback \
  -H "X-API-Key: $FEEDBACK_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"text":"This is terrible"}'

FEEDBACK_DB_PATH=feedback-runtime.sqlite3 uv run python -m production.worker

curl -sS http://127.0.0.1:8000/jobs/YOUR_JOB_ID \
  -H "X-API-Key: $FEEDBACK_API_KEY"
```

The job is `awaiting_approval`. Inspect its proposal before submitting approval:

```bash
curl -sS http://127.0.0.1:8000/jobs/YOUR_JOB_ID/approval \
  -H "X-API-Key: $FEEDBACK_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"approved":true}'

FEEDBACK_DB_PATH=feedback-runtime.sqlite3 uv run python -m production.worker
```

Check the completed result with the same job ID:

```bash
curl -sS http://127.0.0.1:8000/jobs/YOUR_JOB_ID \
  -H "X-API-Key: $FEEDBACK_API_KEY"
```

Expect `completed` and a `pending_review` record.

The saved decision returns the job to the queue. The worker rechecks the action
against the immutable approved proposal. SQLite checks approval and lease
ownership in the same transaction that creates the review item.

Use `{"approved":false}` to reject, or cancel pending work:

```bash
curl -sS -X POST http://127.0.0.1:8000/jobs/YOUR_JOB_ID/cancel \
  -H "X-API-Key: $FEEDBACK_API_KEY"
```

## States and boundaries

Approval waiting releases the lease and does not consume an execution attempt.
Decisions are final for an operation ID. Changed details require a new proposal.

Cancellation is stored as `failed` with `cancellation_requested=true` and a
cancellation reason. It prevents the local database side effect and revokes the
claim. Ongoing model computation may finish before the worker observes revocation.

Escalation is stored as `failed` with an escalation reason. Operators can read
the result through the job endpoint. Sending an alert or creating an external
ticket needs an integration.

The worker checks a trusted service permission set before executing an action.
SQLite review creation is the durable tool action in this workflow. The worker
uses the existing predictor and decision policy, then applies execution controls
before saving the review. External tools need their own idempotency and permission
enforcement.

The default lease is 30 seconds, with no heartbeat renewal. Retry classification
currently covers inference timeouts and connection errors before durable effects.
Expired claims count toward the three-attempt limit. A worker invocation processes
one eligible job. A scheduler must invoke it again after a saved retry time.
