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

## Shared runtime setup

The runtime now uses tenant credentials, worker leases, retry scheduling, and
durable approval. Follow the [Category 03 setup and manual workflow](../category_03_reliability_and_access/README.md)
to apply all five migrations and configure the API key.

The automated exercise below explicitly disables approval in its API instance
so it continues to demonstrate queued-job processing in one worker invocation.
It supplies a test credential for authenticated access.

## Run the automated exercise

```bash
uv run python -m production.01_workflow_runtime.restart_and_resume
```

The exercise uses a temporary database, makes requests through FastAPI's test
client, and starts the worker in a separate process. Expect a final line
confirming that the job completed with exactly one pending review.

This exercise covers jobs that are still queued when the worker starts.
For a job left in `running` after a crash, run Category 03's crash-recovery exercise.
