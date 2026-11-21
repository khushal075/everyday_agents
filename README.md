# Everyday Agents

Understand how agents work through **15 runnable Python examples**, then follow
one feedback agent through persistence, recovery, approval, observability, and
container deployment.

The project includes a sentiment application with a rules baseline and a trained
TF-IDF + logistic-regression predictor. The production workflow reuses the
sentiment predictor and decision policy to process jobs through an API and worker.

## Start here

| Goal | Start with |
| --- | --- |
| Understand agent concepts one at a time | [Phase 1 examples](examples/concepts/README.md) |
| Run sentiment prediction and training | [Sentiment implementation](src/everyday_agents/agents/sentiment/README.md) |
| Follow a persistent job through failures and approval | [Phase 2 overview](production/README.md) |
| Run the containerized application | [Deployment setup](production/category_05_deployment_and_operations/README.md) |
| Back up, restore, or investigate the service | [Operations runbook](production/category_05_deployment_and_operations/runbook.md) |

## Quick start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). Run from the repository
root:

```bash
uv sync --locked
uv run everyday-agents --version
uv run everyday-agents sentiment run --text "This is terrible"
```

The sentiment CLI predicts, selects an action, creates an in-memory feedback
record, and verifies the result. Negative or uncertain feedback is prepared
for review. Positive or neutral predictions are recorded.

Run commands through `uv` without activating the environment. For IDE use,
select `.venv/bin/python` or `.venv/Scripts/python.exe` on Windows.

## Phase 1 · Agent concepts

The 15 exercises cover rules and learned decisions, tools, policy, authorization,
approval, verification, retrieval, RAG, reranking, memory, replanning, safe
recovery, checkpoints, coordination, MCP, and evaluation.

Start with the first exercise:

```bash
uv run python examples/concepts/01_rule_based_agent.py
```

Try safe recovery or evaluation independently:

```bash
uv run python examples/concepts/11_safe_recovery.py
uv run python examples/concepts/15_evaluation_and_observability.py
```

Examples 07–09 use a locally running Ollama model. The
[concepts README](examples/concepts/README.md) gives setup, individual run commands,
and changes to try.

## Phase 2 · Production behavior

One feedback application demonstrates what happens after an HTTP request is
accepted. Jobs persist in SQLite while a separate worker processes them.
Review actions can wait for approval across process restarts.

| Category | What it demonstrates |
| --- | --- |
| [01 · Workflow runtime](production/01_workflow_runtime/README.md) | API submission, persistent jobs, and processing work saved while the worker was offline. |
| [02 · Models, retrieval, and tools](production/category_02_models_retrieval_and_tools/README.md) | Policy search, bounded context, response validation, permitted routes, and reproducible model/tool failures. |
| [03 · Reliability and access](production/category_03_reliability_and_access/README.md) | Leases, stale-token rejection, bounded retries, tenant permissions, durable approval, and cancellation. |
| [04 · Evaluation and observability](production/category_04_evaluation_and_observability/README.md) | Regression cases, component events, metric summaries, real HTTP load, inference batching, and coordinated checks. |
| [05 · Deployment and operations](production/category_05_deployment_and_operations/README.md) | Versioned migrations, containers, service health, approval smoke testing, alerts, backup, and restore. |

Run isolated exercises before configuring a persistent deployment:

```bash
uv run python -m production.01_workflow_runtime.restart_and_resume
uv run python -m production.category_02_models_retrieval_and_tools.model_and_tool_failures
uv run python -m production.category_03_reliability_and_access.crash_and_retry
uv run python -m production.category_03_reliability_and_access.permissions_and_approval
uv run python -m production.category_04_evaluation_and_observability.evaluate
uv run python -m production.category_04_evaluation_and_observability.service_load
```

The production exercises use separate processes and real local HTTP where stated.
The deployment uses one host and SQLite. Category 02's model responses are
scripted and its review tool is in memory. Connecting real retrieval and external
model/tool execution to the persistent worker remains integration work.

### Authentication and notifications

API-key authentication is available for local exercises. Optional OIDC bearer
authentication validates RS256 access tokens against a configured issuer, API
audience, and JWKS endpoint, then applies tenant and permission checks.

The alert checker can send JSON webhooks with durable delivery IDs and bounded
retries. Receivers must deduplicate repeated delivery IDs. Notifications are
enabled explicitly with `--notify`.

These adapters are verified using local HTTP fixtures, ephemeral RSA keys,
and a bearer-authenticated API/worker smoke test. Hosted provider and receiver
verification requires their configuration and credentials. Setup is documented
in the [deployment README](production/category_05_deployment_and_operations/README.md).

## Train and evaluate a sentiment model

Train on the included synthetic examples and save the features and model:

```bash
uv run everyday-agents sentiment train \
  --data data/samples/sentiment/feedback.jsonl \
  --output artifacts/models/sentiment-v1

uv run everyday-agents sentiment run \
  --model artifacts/models/sentiment-v1 \
  --text "Great helpful service"
```

Choose a new output directory when that destination already exists.
`uv run python -m everyday_agents` supports the same arguments.
The older `examples/sentiment_demo.py` prints a JSON array.

Training splits rows 80/10/10 using seed 42, fits the training partition, and
reports validation results. Add `--evaluate-test` for the final test report
after model choices are fixed.

Evaluate a saved model using a separate labelled holdout:

```bash
uv run everyday-agents sentiment evaluate \
  --model artifacts/models/sentiment-v1 \
  --data path/to/independent-holdout.jsonl
```

Every supplied row is evaluated. Holdout independence must be established by
the caller. See [evaluation](docs/evaluation.md) and
[score definitions](docs/score-definitions.md).

## Verified behavior and limits

Local verification on 21 November 2026 passed **132 software tests**.
The Docker exercise verified non-root startup, authenticated approval and
completion, restart persistence, SQLite backup/restore, and alert exit codes.

The 72 sentiment examples are synthetic. Broader model quality needs
representative data and evaluation. The baseline has limited handling of
negation and sarcasm. The learned model produces uncalibrated probabilities
and applies no low-confidence abstention threshold.

Dataset splitting is row-level. Real datasets need appropriate user, group,
and time boundaries to prevent leakage. Model artifacts use joblib, so load
trusted files using matching runtime versions. Artifact saving protects existing
destinations but can leave partial files after a failure.

Telemetry is best effort and can have gaps. The workflow database is the source
of job state. Queue delay in the load exercise is estimated from event timestamps.
Single-host results do not establish multi-host capacity or operational guarantees.

The original `v0.1.0` tag identifies the historical sentiment-focused release.
Current production exercises extend that application.

## Development and checks

```bash
uv run --locked python -m unittest discover -s tests -v
uv build
```

The existing checks workflow tests Python 3.12/3.13/3.14, builds distributions,
and checks a clean wheel installation. The production workflow builds the image,
starts Compose services, and runs the deployed smoke and health checks.
Hosted CI runs when the commits reach GitHub.

## Repository layout

```text
everyday_agents/
├── examples/concepts/              # 15 concept exercises and the MCP server
├── production/
│   ├── api.py                     # Authenticated feedback endpoints
│   ├── store.py                   # Persistent jobs and transactional execution
│   ├── worker.py                  # One bounded processing attempt
│   ├── 01_workflow_runtime/
│   ├── category_02_models_retrieval_and_tools/
│   ├── category_03_reliability_and_access/
│   ├── category_04_evaluation_and_observability/
│   └── category_05_deployment_and_operations/
├── src/everyday_agents/
│   ├── core/                      # Agent contracts and orchestration
│   ├── ml/                        # Data, training, evaluation, and artifacts
│   └── agents/sentiment/           # Sentiment reference application
├── tests/                         # Unit, integration, and operations checks
├── data/                          # Synthetic samples and schema
├── docs/                          # Architecture and background guides
└── scripts/                       # Installation verification
```

[Architecture](docs/architecture.md) · [Contributing](CONTRIBUTING.md) ·
[Changelog](CHANGELOG.md)
