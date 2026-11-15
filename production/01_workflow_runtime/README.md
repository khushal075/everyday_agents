# 01 · Workflow runtime

A customer submits feedback while the worker is offline. The API saves the
request in SQLite and returns a job ID. When the worker starts, it reads the
saved job, runs the sentiment agent, and saves the outcome. Negative feedback
that the policy flags for review also gets a review record.

## What each file does

| File | Responsibility |
| --- | --- |
| [api.py](../api.py) | Accept feedback and report job status and any review result. |
| [worker.py](../worker.py) | Claim queued jobs and run the existing sentiment agent. |
| [store.py](../store.py) | Give both processes access to the same database and manage job state changes. |
| [001_initial.sql](migrations/001_initial.sql) | Create the job and review tables. |
| [restart_and_resume.py](restart_and_resume.py) | Exercise the workflow across separate processes. |

## Apply the schema

Run this from the repository root. Use a fresh database filename for this
one-time migration.

```bash
sqlite3 feedback-runtime.sqlite3 < production/01_workflow_runtime/migrations/001_initial.sql
sqlite3 feedback-runtime.sqlite3 '.tables'
```

Expect to see `feedback_jobs` and `review_records`. The API and worker will
need the same database path. Enable SQLite foreign keys on every connection,
and save a successful job's outcome and any review record in one transaction.

## Run the workflow

From the repository root, start the API after applying the schema above.

```bash
uv sync --locked
FEEDBACK_DB_PATH=feedback-runtime.sqlite3 uv run uvicorn production.api:app
```

In a second terminal, submit feedback while the worker is stopped.

```bash
curl -i http://127.0.0.1:8000/feedback \
  -H 'Content-Type: application/json' \
  -d '{"text":"This is terrible"}'
```

The API returns HTTP 202. Copy the returned job ID in place of `YOUR_JOB_ID`.
Check that the job is queued, run the worker once, then check the same job
again.

```bash
curl -sS http://127.0.0.1:8000/jobs/YOUR_JOB_ID
FEEDBACK_DB_PATH=feedback-runtime.sqlite3 uv run python -m production.worker
curl -sS http://127.0.0.1:8000/jobs/YOUR_JOB_ID
```

With a fresh database, the job moves from `queued` to `completed` and gets
one `pending_review` record. The worker handles one queued job per run.

## Run the automated exercise

```bash
uv run python -m production.01_workflow_runtime.restart_and_resume
```

The exercise uses a temporary database, makes requests through FastAPI's test
client, and starts the worker in a separate process. Expect a final line
confirming that the job completed with exactly one pending review.

This exercise covers jobs that are still queued when the worker starts.
Recovering a job left in `running` after a crash needs a worker lease and
retry handling, which belong to the reliability category.
