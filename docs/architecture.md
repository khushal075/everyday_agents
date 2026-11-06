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
Planned state/tracing/registry files remain placeholders until needed.

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
