# Architecture

## Core

`schemas.py` defines Decision, ActionResult, and generic AgentRun records.
`agent.py` defines Predictor, Policy, and Tool protocols, and orchestrates:

```text
input → predictor.predict → policy.decide → tool.execute → tool.verify → AgentRun
```

One run performs one cycle. Execution failures skip verification; failed
verification produces an unsuccessful result. Exceptions propagate and stop later
stages. No automatic retries or side-effect rollback are attempted. An exception
after execution may leave an action completed, so inspect before retrying.

Prediction types are domain-specific. Tool implementations validate supported
actions and parameters and enforce any required approval before side effects.
The reusable core stays small. Persistence, leases, access, and telemetry are
implemented by the reference application under `production/`. They do not change
the one-cycle contract of the core Agent.

## ML

The shared ML package provides a Trainer protocol, dataset loading, seeded
splitting, classification metrics, and artifact persistence using caller-supplied
serialization. It reuses the core Predictor contract. It does not select models,
train automatically, or prescribe domain labels.

## Sentiment

The baseline counts recognised English words. The learned predictor wraps a
fitted sklearn TF-IDF/classifier pipeline. Both expose a sentiment label to the
policy; their other fields remain distinct. Policy routes negative/uncertain
feedback to prepare_review and positive/neutral feedback to record. FeedbackTool
stores immutable domain records in memory and compares returned fields with
stored records during verification.

Training happens outside the agent loop. The CLI combines training, validation
comparison, and optional artifact saving. The evaluate command loads a fixed model
and uses caller-supplied independent data. It never fits a model.

## Learning and production tracks

`examples/concepts/` contains 15 runnable concept exercises and a companion MCP
server. They isolate rules, learned decisions, tools, approval, verification,
retrieval, RAG, reranking, memory, planning, recovery, checkpoints, coordination,
MCP, and evaluation. Their README states dependencies and simulation boundaries.

`production/` contains the integrated reference application and five categories
of operational exercises. The original sentiment package and CLI remain usable.
The `v0.1.0` tag still identifies the historical sentiment-focused release.

## Persistent reference application

```text
Authenticated HTTP request
  → SQLite job (tenant, workflow mode, approval requirement)
  → worker claim (token, expiry, attempt)
  → sentiment prediction/policy OR policy retrieval/context/model validation
  → permission check
  → immutable proposal and optional approval wait
  → new worker restores exact saved policy proposal
  → transactional local execution
  → durable result verification and correlated events
```

The default workflow uses the sentiment baseline. Policy mode uses
`feedback_workflow.py` to prepare an action from retrieved evidence. Its routing
model can use an explicit scripted fixture or an Ollama HTTP generator. Output
validation checks route, reason, citation, and the configured permitted route.

The policy proposal stores feedback, route, reason, selected citation, and a full
evidence snapshot as immutable action parameters. Resume does not repeat inference.
Approval is bound to this exact proposal. Lease validity, cancellation, saved
proposal equality, and required approval are checked again inside the transaction
that inserts the review and completes the job. The persistent tool verifies the
saved review's metadata after commit.

A model/network failure before execution can trigger a bounded retry. Reclaimed
workers use a new ownership token. No evidence produces an explicit no-review
record outcome. Invalid recommendations escalate without review creation. A
post-commit verification failure is visible but does not replay committed work.

The API supports configured API-key identities and optional OIDC access tokens.
Tenant checks protect reads, proposals, approvals, and cancellation. Telemetry is
best effort and separate from workflow state. Container services, migrations,
health checks, alerts, and backup/restore procedures complete the local reference.

This is a single-host SQLite implementation with a local review tool. Live model
quality, hosted identity/notification configuration, and external business systems
require their own verification. See the [coverage matrix](coverage-matrix.md) and
[production overview](../production/README.md) for evidence and boundaries.
