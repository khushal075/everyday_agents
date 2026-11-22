# Learning path

Learn how an agent works, how its Python implementation is structured, and what
changes when that work must survive failures and approval.

You can begin with behavior and results, then follow the code links when you
want to understand the implementation. The three layers reuse the same ideas
at increasing levels of responsibility.

| Layer | Location | Learning outcome |
| --- | --- | --- |
| 1. Understand the concepts | `examples/concepts/` | Explain one responsibility at a time. |
| 2. Structure the implementation | `src/everyday_agents/` | Assemble and evaluate a reusable sentiment agent. |
| 3. Operate the system | `production/` | Follow persistent work through ownership, approval, recovery, and verification. |

For a behavior-first introduction, read [one customer request](request-walkthrough.md).

## Before you start

Basic Python functions, classes, and terminal commands are enough for the first
examples. Type annotations, protocols, and generics become useful in layer 2;
you can learn them while following the concrete sentiment implementation.
HTTP, SQL transactions, and processes become relevant in layer 3.

Use Python 3.12+ and uv. From the repository root:

```bash
uv sync --locked
```

The default sentiment and integrated policy demonstrations need no hosted model
credentials. Phase 1 examples 07–09 need a running local Ollama model. Docker is
needed for the container deployment lab. Read each example's stated setup.

## 1. Understand the concepts

Start with the [15-example guide](../examples/concepts/README.md), which includes
every script, run command, and expected behavior.

| Lessons | Question to answer | Try and observe |
| --- | --- | --- |
| 01–05 · Decisions, tools, approval, verification | Who predicts, who decides, who acts, and who checks? | Reject an approval in 04; observe the failed move verification in 05. |
| 06–09 · Retrieval, RAG, reranking, memory | What information reaches the model, and where did it come from? | Ask about a warranty absent from the manual; ask a follow-up in the same session. |
| 10–12 · Planning, recovery, checkpoints | How does the agent respond when its plan or process stops working? | Observe a blocked route; compare timeouts before and after delivery; resume a saved approval. |
| 13–15 · Coordination, MCP, evaluation | How do components cooperate, and how do we detect mistakes? | Inspect specialist reports and discovered tools; change the evaluation threshold. |

Run the first example:

```bash
uv run python examples/concepts/01_rule_based_agent.py
```

Then introduce an intentional evaluation regression:

```bash
uv run python examples/concepts/15_evaluation_and_observability.py
uv run python examples/concepts/15_evaluation_and_observability.py --threshold 10
```

The second command should report 3/4 passing cases and exit with code 1. Explain
why changing a decision rule should not automatically change the expected result.

**Checkpoint:** explain why prediction, action selection, permission, execution,
and verification belong to separate responsibilities. Identify which examples
use a trained model, an LLM, deterministic rules, or a simulated environment.

## 2. Structure the implementation

The reusable package is `src/everyday_agents/`. Read the concrete sentiment flow
alongside its shared contracts. It makes the abstractions easier to understand.

### Follow one agent run

```bash
uv run everyday-agents sentiment run --text "This is terrible"
uv run everyday-agents sentiment run --text "Great helpful service"
```

The default predictor is a rules baseline. Negative or uncertain predictions
prepare feedback for review; positive or neutral predictions record it. These
CLI actions use an in-memory tool and do not create a durable approval workflow.

| Reading order | File | Responsibility |
| --- | --- | --- |
| 1 | [Sentiment assembly](../src/everyday_agents/agents/sentiment/agent.py) · `create_agent` | Supply the predictor, policy, and tool to the shared Agent. |
| 2 | [Core records](../src/everyday_agents/core/schemas.py) · `Decision`, `ActionResult`, `AgentRun` | Describe the selected action, tool outcome, and completed cycle. |
| 3 | [Core orchestration](../src/everyday_agents/core/agent.py) · `Predictor`, `Policy`, `Tool`, `Agent.run` | Define contracts and coordinate predict → decide → execute → verify. |
| 4 | [Sentiment schemas](../src/everyday_agents/agents/sentiment/schemas.py) and [baseline](../src/everyday_agents/agents/sentiment/baseline.py) | Define domain outputs and produce a rules-based prediction. |
| 5 | [Sentiment policy](../src/everyday_agents/agents/sentiment/policy.py) · `SentimentPolicy` | Translate a sentiment label into a `Decision`. |
| 6 | [Sentiment tools](../src/everyday_agents/agents/sentiment/tools.py) · `FeedbackTool` | Execute supported actions and verify saved in-memory records. |

Try changing the input to a sentence whose meaning depends on negation. Compare
the output with your own interpretation. The exercise exposes a model limitation;
a successful tool result does not establish that the sentiment prediction is correct.

### Follow training separately from inference

| Shared ML file | What to understand |
| --- | --- |
| [interfaces.py](../src/everyday_agents/ml/interfaces.py) | How the Trainer contract relates training to a predictor. |
| [datasets.py](../src/everyday_agents/ml/datasets.py) | How CSV/JSONL records are loaded and invalid data is reported. |
| [splitting.py](../src/everyday_agents/ml/splitting.py) | Why training, validation, and test rows have separate roles. |
| [metrics.py](../src/everyday_agents/ml/metrics.py) | What precision, recall, F1, support, and accuracy describe. |
| [artifacts.py](../src/everyday_agents/ml/artifacts.py) | How metadata and caller-supplied model serialization support saving and loading. |

Then follow sentiment [features](../src/everyday_agents/agents/sentiment/features.py),
[training](../src/everyday_agents/agents/sentiment/train.py),
[prediction and persistence](../src/everyday_agents/agents/sentiment/predictor.py), and
[evaluation](../src/everyday_agents/agents/sentiment/evaluation.py).

```bash
uv run everyday-agents sentiment train \
  --data data/samples/sentiment/feedback.jsonl \
  --output artifacts/models/learning-sentiment-v1

uv run everyday-agents sentiment run \
  --model artifacts/models/learning-sentiment-v1 \
  --text "Great helpful service"
```

Choose a fresh output directory on repeated training runs. The sample data is
synthetic. Use validation for model choices; reserve the test split for the final
evaluation after those choices. See [evaluation](evaluation.md) for details.

**Exercise:** compare baseline and learned predictions on the same few sentences.
Explain why disagreement alone tells you neither model is necessarily correct.

**Checkpoint:** explain how replacing the predictor leaves the policy/tool
contracts unchanged, why training sits outside the agent run, and what a saved
model artifact contains. Find where failed execution skips verification.

## 3. Operate the system

Start with the [request walkthrough](request-walkthrough.md), then explore the
[five production categories](../production/README.md).

```bash
uv run python -m production.category_02_models_retrieval_and_tools.integrated_feedback
```

This isolated demonstration uses the actual API routes through an in-process HTTP
client, temporary SQLite databases, and separate worker processes. Its default
fixture generator performs no inference. The walkthrough explains how to select
Ollama and which behavior is being verified.

| Category | Question to answer | Exercise |
| --- | --- | --- |
| [01 · Runtime](../production/01_workflow_runtime/README.md) | Why can an API accept work while the worker is offline? | Run `restart_and_resume`; locate queued and completed state. |
| [02 · Models, retrieval, tools](../production/category_02_models_retrieval_and_tools/README.md) | Which evidence supports the route, and how is the result checked? | Run the integrated example with `--reject` and with unmatched feedback. |
| [03 · Reliability and access](../production/category_03_reliability_and_access/README.md) | Who owns the job and who may approve or cancel it? | Run `crash_and_retry` and `permissions_and_approval`; explain why a stale owner cannot write. |
| [04 · Evaluation and observability](../production/category_04_evaluation_and_observability/README.md) | How do we distinguish correct behavior, failed work, and slow work? | Run evaluation, inspect trace stages, and compare queue delay with processing duration. |
| [05 · Deployment and operations](../production/category_05_deployment_and_operations/README.md) | How do we start, inspect, recover, and upgrade the service? | Follow Compose setup, run the smoke test, then practice the documented restart procedure. |

**Checkpoint:** explain why accepting a request differs from completing it, why
approval binds exact saved parameters, and why a timeout alone cannot tell you
whether an external action happened. Identify which checks prove workflow
behavior and which would require representative model-quality data.

## How the layers connect

The sentiment CLI uses the shared core Agent for one cycle. The production
sentiment worker reuses its predictor and policy but coordinates persistent
execution itself so approval and leases surround the database transaction.
Policy mode adds a separate `FeedbackWorkflow` for retrieval and routing. It
also uses the persistent worker, approval, storage, and telemetry components.
It does not run through the sentiment model or the core `Agent.run` method.

Both layers teach the same responsibilities; their execution boundaries reflect
the different persistence requirements. Use the [architecture guide](architecture.md)
when following these connections in code.

## Explain the design choices

Read the [architecture decision records](adr/README.md) after following the
workflow. For each decision, explain the problem it solves, the trade-off it
introduces, and the requirement that would make you revisit it.

## What this learning path establishes

The local reference includes 15 concept examples, a reusable sentiment package,
and the five-category production track. [Coverage](coverage-matrix.md) records
implemented behavior and limits. Representative model quality, hosted integrations,
and multi-host guarantees need their own evidence. The historical `v0.1.0` tag
continues to identify the original sentiment release.
