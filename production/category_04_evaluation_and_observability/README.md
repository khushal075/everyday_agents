# 04 · Evaluation and observability

Run fixed workflow expectations, follow an approved job, measure model
throughput, and observe independent checks contributing to a routing decision.

## Files

| File | Purpose |
| --- | --- |
| `telemetry.py` | Emit timestamped JSON events to a text stream and optional shared SQLite database. |
| `metrics.py` | Validate stored events and summarize stage outcomes, durations, and distinct job completions. |
| `fixtures/evaluation_cases.jsonl` | Define five baseline workflow cases and their expected outputs. |
| `evaluate.py` | Compare sentiment, action, tool status, and tool success against each case. |
| `trace_job.py` | Observe submission, approval waiting, approval, and completion for one persistent job. |
| `service_load.py` | Exercise concurrent HTTP submissions against a real API process and separate worker. |
| `load_and_batching.py` | Compare individual, batched, and concurrent inference using a fitted model. |
| `coordinated_checks.py` | Run sentiment prediction and policy retrieval independently, then combine their findings. |

## Setup

Use Python 3.12 or newer and run these commands from the repository root.

```bash
uv sync --locked
```

The trace exercise creates a temporary SQLite database, applies the migrations,
and supplies its own test credential. Workers run in separate processes. API
calls use FastAPI's test client. Its database is removed after the exercise.

## Evaluate the baseline workflow

```bash
uv run python -m production.category_04_evaluation_and_observability.evaluate
```

Expect five passing cases and `Summary: 5 / 5 passed`. Text with no recognized
sentiment words and text with balanced evidence receive `uncertain` from the
baseline and are routed for review.

| Exit code | Meaning |
| --- | --- |
| 0 | Every case passed. |
| 1 | A workflow output differed from an expectation, or execution raised an error. |
| 2 | The fixture could not be read or validated. |

To check regression detection, copy the fixture to a temporary location and
change the positive case's `expected_action` from `record` to
`prepare_review`. Pass the copied fixture with `--cases`:

```bash
uv run python -m production.category_04_evaluation_and_observability.evaluate --cases /path/to/copied_cases.jsonl
```

Expect four passing cases, a failed positive case, and exit code 1. Duplicate
case IDs and empty fixtures are rejected.

## Follow an approved job

```bash
uv run python -m production.category_04_evaluation_and_observability.trace_job
```

The exercise submits negative feedback, starts a worker, checks the saved
proposal, approves it, and starts a second worker. It reads the shared event
database and verifies the presence and ordering of actual component events:

- `store.queued`, `store.claimed`, and `store.awaiting_approval`.
- `worker.prediction`, `worker.decision`, and `worker.permission`.
- `store.approved` and `worker.approval`.
- `store.completed`, `worker.execution`, and `worker.completed`.
- API submission, lookup, and approval request events.

Every job event uses the job ID as its `run_id`. The exercise checks tenant
correlation and exactly one successful worker completion. The current successful
path produces 20 component events. Worker subprocess output is captured while
events remain available in the shared database.

API durations measure request handling. Worker stage durations measure inference,
decision-making, permissions, and execution separately. Store transition events
are emitted after the transaction commits. Event writes are best effort and
report logging failures to stderr. A process exit between a workflow commit and
its event write can leave a gap in the trace.

## Instrument the running services

Set the same absolute event database path in the API and worker environments:

```bash
export FEEDBACK_TELEMETRY_DB="$PWD/telemetry.sqlite3"
```

Use the Category 03 commands to configure credentials and start the API and
worker. Their telemetry defaults to stderr when this variable is absent.
Use a separate event database from the workflow database.

To select the trace exercise's event destination:

```bash
uv run python -m production.category_04_evaluation_and_observability.trace_job --database /tmp/feedback-trace.sqlite3
uv run python -m production.category_04_evaluation_and_observability.metrics --database /tmp/feedback-trace.sqlite3
```

Metrics group unique events by stage, count failed and error outcomes, and
calculate minimum, median, nearest-rank p95, and maximum duration. Completed jobs
are deduplicated by tenant and job ID using successful `worker.completed` events.

Runtime events omit credentials, feedback text, and approval parameters.
Rejected API requests receive separate request run IDs, without attaching an
unverified job ID. Their errors identify the HTTP status.

## Read structured events

Events contain a UTC timestamp, run ID, optional job and tenant IDs, stage,
attempt, outcome, duration in milliseconds, and optional exception type.
The emitter uses `tenant_id` consistently. Each event has a unique `event_id`.

JSON events go to stderr. Human-readable results go to stdout. To capture the
evaluation events:

```bash
uv run python -m production.category_04_evaluation_and_observability.evaluate 2> /tmp/everyday-agents-evaluation.jsonl
```

The trace script may also write a dependency deprecation warning to stderr.
Consumers of captured trace output should account for that warning when parsing
JSON lines.

## Measure model throughput

```bash
uv run python -m production.category_04_evaluation_and_observability.load_and_batching
uv run python -m production.category_04_evaluation_and_observability.load_and_batching --texts 3000 --batch-size 64 --workers 4
```

The benchmark trains the existing TF-IDF and logistic-regression pipeline using
the sample data. Training and reference probability generation happen before
the timer starts. It repeats three input texts to create the requested workload.

It measures three modes:

1. Individual prediction with one worker.
2. Batched prediction with one worker.
3. Individual prediction with a thread pool.

Each mode reports elapsed time and texts per second. All modes must return
equivalent class probabilities within the configured numerical tolerance.
Thread-pool setup is included in the concurrent measurement.

Results depend on the machine and workload. This exercise measures fitted-model
inference. API request latency, queue delay, worker throughput, batch collection
delay, and production capacity require their own measurements. Each mode runs
once, so repeat the benchmark to inspect variability.

## Measure the running service

```bash
uv run python -m production.category_04_evaluation_and_observability.service_load
uv run python -m production.category_04_evaluation_and_observability.service_load --requests 100 --concurrency 8 --timeout 60
```

The exercise creates temporary workflow and telemetry databases, applies all
migrations, generates its own API credential, and starts a real Uvicorn process
on an OS-assigned loopback port. A separate persistent worker polls every
10 milliseconds. Startup completes before the workload timer begins.

The client sends concurrent authenticated HTTP requests containing positive
feedback. These jobs take the automatic `record` path. Approval and review
creation are covered by the trace and Category 03 exercises.

| Report field | Measurement |
| --- | --- |
| `submitted` and `accepted` | Requests attempted and unique job IDs acknowledged by HTTP 202. |
| `submission_failures` | Requests that fail or return an unexpected response. |
| `completed_jobs` and `failed_jobs` | Final database states for accepted jobs. |
| `submission_http_latency_ms` | Minimum, median, nearest-rank p95, and maximum HTTP submission duration. |
| `workload_seconds` | Time from starting submissions until accepted jobs reach terminal states, including polling delay. |
| `completed_jobs_per_second` | Completed jobs divided by workload seconds. |
| `observed_queue_delay_ms` | Estimated delay between `store.queued` and the first `store.claimed` event. |
| `queue_delay_samples` | Jobs with usable queue timestamp pairs. |
| `unusable_queue_delay_samples` | Jobs whose queue events are missing or out of order. |
| `worker_processing_ms` | Duration summaries from successful `worker.completed` events. |

Queue estimates use event emission timestamps from processes on the same host.
Scheduling between a commit and its event write can affect the estimate.
Out-of-order samples are counted explicitly and excluded from duration
statistics. The worker's 10-millisecond polling interval also contributes to
observed waiting time.

The exercise verifies each completed job through HTTP after the workload timer
stops. It also checks that completion telemetry matches database results, that
positive feedback created no review records, and that foreign keys remain
valid. An ambiguous submission outcome fails verification instead of being
counted as an acknowledged job.

The JSON report goes to stdout. Service logs and databases live in a temporary
directory. Cleanup stops and reaps both child processes before removing it.
The command exits with code 1 if requests or jobs fail, startup or completion
times out, or verification fails.

This is one local API process, one worker, and SQLite. The workload uses a fixed
positive sentence. The measured throughput includes submission and queue
draining, so it describes this complete local workload. Repeat runs and increase
concurrency to explore variability and contention. Approval latency, external
model calls, external tools, and multi-host capacity need their own workloads.

## Observe coordinated checks

```bash
uv run python -m production.category_04_evaluation_and_observability.coordinated_checks
```

The coordinator runs baseline sentiment prediction and keyword policy retrieval
in two threads. It emits timings for each check and the overall operation.

Duplicate-charge feedback proposes `prepare_review`. Positive feedback with
no matching policy proposes `record`. The script prints the findings used for
the decision. Permissions, approvals, and durable execution belong to the
persistent workflow.

## Verified scope and remaining work

Category 04 now includes fixed-case evaluation, component instrumentation,
persistent event aggregation, job trace verification, concurrent HTTP service
load, model batching benchmarks, and coordinated component checks.

The five synthetic cases define software expectations. Model quality needs
representative evaluation data. Metric summaries describe stored events and may
contain gaps after logging failures. The workflow database remains the source
of job state.

Deployment wiring, external monitoring and alerting, and dashboards belong to
Category 05. Real model and external tool integration remain Phase 2 integration
work.
