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
State persistence, tracing, and registries will be introduced when implemented;
no empty modules are retained for those future requirements.

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

`examples/concepts/` is the Phase 1 learning area. No examples are implemented
yet; future lessons are independent, complete programs with explicit limits.
`tests/concepts/` will hold their checks.

`production/` currently documents Phase 2 scope only. Future application wiring,
configuration, deployment, and operational exercises belong there, with reusable
Python functionality kept in `src/everyday_agents/`. A directory name is not a
production-readiness claim. See the coverage matrix for evidence and gaps.

The implemented sentiment package retains its existing paths and CLI behaviour.
Future domain applications are tracked in the roadmap rather than empty modules.
