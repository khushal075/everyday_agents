# 04 · Evaluation and observability

Run fixed workflow expectations, follow an approved job, measure model
throughput, and observe independent checks contributing to a routing decision.

## Files

| File | Purpose |
| --- | --- |
| `telemetry.py` | Emit timestamped JSON events to a text stream. |
| `fixtures/evaluation_cases.jsonl` | Define five baseline workflow cases and their expected outputs. |
| `evaluate.py` | Compare sentiment, action, tool status, and tool success against each case. |
| `trace_job.py` | Observe submission, approval waiting, approval, and completion for one persistent job. |
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

The exercise submits negative feedback, starts a worker, checks that approval is
required, saves approval, and starts a second worker. It verifies the final
review record and emits four correlated events:

- `feedback.submitted`
- `worker.awaiting_approval`
- `approval.saved`
- `worker.completed`

Each event shares the same `run_id` and `job_id`. Expect a final
`PASS` message and the trace run ID.

These events are emitted by the exercise as it observes API and process
boundaries. Worker-stage durations include subprocess startup and the subsequent
status lookup. Internal API, database, and worker spans still need instrumentation.

## Read structured events

Events contain a UTC timestamp, run ID, optional job and tenant IDs, stage,
attempt, outcome, duration in milliseconds, and optional exception type.
The current emitter accepts the tenant through its `team_id` argument and
serializes it as `tenant_id`.

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

The scripts demonstrate baseline regression detection, observed job lifecycle
events, local model inference benchmarking, and concurrent component checks.

The five synthetic cases define expected software behavior. Broader model
quality needs representative evaluation data. Further work includes internal
service instrumentation, API and queue load measurements, metric aggregation,
alerting, and deployment integration.
