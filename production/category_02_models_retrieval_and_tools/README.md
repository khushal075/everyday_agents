# 02 · Models, retrieval, and tools

Follow customer feedback from policy search to an approved, persistent review.
The shared production worker now runs either the original sentiment workflow or
this policy workflow. Each job stores its workflow mode when submitted.

## Complete workflow

1. The authenticated API saves the feedback and tenant ownership in SQLite.
2. A worker claims the job with an expiring ownership token.
3. Policy retrieval ranks Markdown sections; the context builder bounds evidence.
4. The generator recommends a route, reason, and citation as JSON.
5. Validation checks the response, citation, and permitted policy route.
6. The store saves an immutable proposal containing the route and full evidence snapshot.
7. When approval is required, the worker releases its lease and waits.
8. An authorized caller approves or rejects the exact saved proposal.
9. A fresh worker restores that proposal without retrieval or inference.
10. Execution rechecks ownership, cancellation, proposal equality, and approval
    inside the transaction that creates the review and completes the job.
11. The tool reads the saved review back and verifies its route and citation.
    Correlated events make preparation, restoration, execution, and verification visible.

No evidence produces an explicit `record` outcome with reason
`No matching policy evidence; no review created.` The generator is skipped.
This is an unhandled-policy case, not a claim that the customer's issue was resolved.

## Files

| File | Responsibility |
| --- | --- |
| `fixtures/support_policy.md` | Fictional duplicate-charge, refund, and account-access policy. |
| `retrieval.py` | Load Markdown sections and rank exact keyword overlaps. |
| `context.py` | Select complete passages within an evidence character budget. |
| `models.py` | Validate recommendations; provide an explicit fixture generator and a real Ollama HTTP adapter. |
| `tools.py` | Keep the original in-memory teaching tool and provide persistent review execution and verification. |
| `search_support_policy.py` | Demonstrate matching and unmatched queries. |
| `model_and_tool_failures.py` | Reproduce individual model and tool failures without the service. |
| `integrated_feedback.py` | Run the full approval lifecycle with an in-process HTTP client and real worker subprocesses. |
| `../feedback_workflow.py` | Prepare a grounded proposal or restore its saved evidence without inference. |
| `../worker.py` | Coordinate claims, routing, permissions, approval, recovery, and execution. |
| `../store.py` | Persist proposals and atomically commit approved routed reviews. |
| `../01_workflow_runtime/migrations/006_policy_workflow.sql` | Preserve existing sentiment jobs and add workflow selection and review metadata. |

## Run without a model server

From the repository root:

```bash
uv sync --locked
uv run python -m production.category_02_models_retrieval_and_tools.search_support_policy
uv run python -m production.category_02_models_retrieval_and_tools.model_and_tool_failures
uv run python -m production.category_02_models_retrieval_and_tools.integrated_feedback
uv run python -m production.category_02_models_retrieval_and_tools.integrated_feedback --reject
uv run python -m production.category_02_models_retrieval_and_tools.integrated_feedback --text "Can you add dark mode?"
```

The integrated example uses a clearly labelled `fixture` generator by default.
It creates temporary workflow and telemetry databases, submits through the actual
API routes, runs a worker, approves through the API, and starts a fresh worker.
It deliberately disables the model and policy file for resume, proving that the
approved proposal is reused. It checks review count, metadata, foreign keys,
and event correlation, then removes the temporary databases.

| Scenario | Expected outcome | Persistent reviews |
| --- | --- | --- |
| Duplicate charge, approved | `review_created` | 1 |
| Duplicate charge, rejected | `rejected` | 0 |
| Dark-mode request | `no_policy_match` | 0 |

The fixture generator performs no ML inference. It exercises workflow behavior
reproducibly. The original smaller exercises continue to use their in-memory tool.

## Run with real model inference

Start Ollama and make a suitable model available using your existing installation.
Pass its exact installed name, for example `qwen` if that alias exists locally:

```bash
uv run python -m production.category_02_models_retrieval_and_tools.integrated_feedback --generator ollama --model qwen
```

The adapter uses Ollama's [generate endpoint](https://docs.ollama.com/api/generate)
with `stream=false` and `format=json`. Its system message and prompt are strings.
The JSON prompt contains feedback and the retrieved evidence. Model output is
validated independently and cannot directly call the tool.

The default endpoint is `http://127.0.0.1:11434/api/generate`. Configure a trusted
endpoint with `FEEDBACK_OLLAMA_URL`. The default socket timeout is ten seconds;
`FEEDBACK_MODEL_TIMEOUT` accepts a finite value above zero and at most fifteen
seconds. Response reading is capped at one MiB. Redirects are rejected.
Socket timeouts are not a total wall-clock deadline. Lease validation prevents
late inference from committing a review after ownership expires.

Timeouts, network failures, HTTP 429, and HTTP 5xx are eligible for bounded retry.
Invalid responses, unsupported routes, and other HTTP errors escalate without
creating a review. The service performs up to three processing attempts. Model
cold starts may exceed the timeout; warm a suitable model before this exercise.

## Use the persistent service

Follow [Category 05](../category_05_deployment_and_operations/README.md) for credentials,
tracked migrations, and deployment. Stop services and apply migration 006 before
running this version. Existing jobs keep `sentiment`; changing server mode affects
new jobs only. The API selects the workflow; clients cannot change a queued job's mode.

For the API process or container:

```dotenv
FEEDBACK_WORKFLOW_MODE=policy
```

For a reproducible worker:

```dotenv
FEEDBACK_ROUTING_GENERATOR=fixture
```

For real inference, choose `ollama` and configure `FEEDBACK_ROUTING_MODEL` and
`FEEDBACK_OLLAMA_URL` on the worker. Missing real-model configuration fails explicitly;
there is no silent fixture fallback. Once a proposal is saved, resume requires
neither the original model nor rereading the policy file.

The API's job response includes the exact proposal and the persistent review's
operation ID, route, reason, source, and heading. The proposal contains the evidence
snapshot used for the recommendation. This data stays within the tenant-scoped API.
Telemetry omits feedback text, model prompts, and credentials.

## Verification and boundaries

```bash
uv run python -m unittest tests.integration.test_feedback_workflow -v
```

Checks cover approval and rejection, exact proposal reuse, cancellation, tenant
isolation, denied permissions, stale leases, process crashes, retry limits,
invalid citations and routes, and post-commit verification failures. Actual HTTP
fixtures exercise the Ollama adapter through the worker. They verify protocol
behavior, not a particular model's reasoning quality. Live Ollama inference was
not run during the 22 November 2026 verification because no server was listening.

Search uses exact keywords and can miss paraphrases or retrieve irrelevant overlap.
Citation validation establishes which supplied passage was cited. Route checks
establish the configured action permission. Neither proves that the explanation is
semantically supported. Model quality needs representative evaluation data.

The current policy is a shared fictional document, not a tenant-specific document
service. Policy ingestion must be trusted. Review creation is a local SQLite tool;
a refund, CRM, or ticketing API would need its own authorization, idempotency, and
reconciliation contract. This implementation does not issue refunds.

Review insertion and job completion commit together. A read-back verification
failure after commit is reported through a failed worker outcome and telemetry;
it does not replay an already committed action. An operator must investigate it.
The single-host SQLite and best-effort telemetry limits in the other categories
continue to apply.
