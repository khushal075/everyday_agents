# How AI Agents Work: 15 Runnable Python Examples

What happens between giving an agent a task and hearing it say “done”? These examples walk through the steps: deciding what to do, finding information, using tools, asking for permission, and checking what actually happened.

Each script isolates one idea so you can run it, change it, and see the result. Together, they show the building blocks you can combine when designing an agent system.

Start at **01** to build up from the basics, or jump to **11** for safe retries, **12** for approval across restarts, or **15** to see an evaluation catch a regression.

## Set up once

Use Python 3.12 or newer and [uv](https://docs.astral.sh/uv/). From the repository root:

```bash
uv sync --locked
cd examples/concepts
```

Run the commands below from this directory. The project environment includes scikit-learn for Example 02 and the MCP Python SDK for Example 14. **Only Examples 07–09 need Ollama.**

For 07–09, have Ollama running locally at `http://localhost:11434` and a text-generation model installed. If the server isn't already running, start it in another terminal:

```bash
ollama serve
```

Use `ollama list` to find the exact installed model name. In the commands below, `qwen` is a local alias; replace it with your installed model name if you haven't created that alias.

## 01–05: Decide, act, and check

| Example | What to watch for | Run |
| --- | --- | --- |
| [01 · Rules](01_rule_based_agent.py) | The robot decides whether to move or recharge after each observation. | `uv run python 01_rule_based_agent.py` |
| [02 · Learned decisions](02_ml_powered_agent.py) | A small decision tree learns to choose an action from labelled examples. | `uv run python 02_ml_powered_agent.py` |
| [03 · Tools and decision policy](03_tools_and_decision_policy.py) | A policy proposes a tool and named arguments; the executor rejects invalid arguments. | `uv run python 03_tools_and_decision_policy.py` |
| [04 · Permission and approval](04_authorization_and_approval.py) | The role check determines who can recharge. An operator still has to approve the specific recharge. | `uv run python 04_authorization_and_approval.py` |
| [05 · Verify the result](05_verified_feedback.py) | A stuck robot reports a successful move. A second observation exposes the mismatch. | `uv run python 05_verified_feedback.py` |

In **04**, type `yes` to approve or `no` to stop. Run `uv run python 04_authorization_and_approval.py --viewer` to see the permission check block recharge before asking.

## 06–09: Find information and use it

| Example | What to watch for | Run |
| --- | --- | --- |
| [06 · Retrieval](06_retrieval.py) | Keyword search returns passages, their sources, and matching words. Common words can produce irrelevant matches. | `uv run python 06_retrieval.py` |
| [07 · Grounded answers](07_grounded_rag.py) | The agent retrieves passages before asking a model to answer and cite them. This is retrieval-augmented generation (RAG). | `uv run python 07_grounded_rag.py --model qwen "How do I recharge the battery?"` |
| [08 · Reranking](08_reranked_rag.py) | Compare the initial keyword ranking with the reordered list. The model receives the highest-ranked passage. | `uv run python 08_reranked_rag.py --model qwen "How do I recharge the battery?"` |
| [09 · Memory and context](09_memory_and_context.py) | The agent saves the last topic and uses it to interpret a follow-up. | `uv run python 09_memory_and_context.py --model qwen` |

In **07** or **08**, try replacing the question with `What is the warranty?` to see the agent stop when it finds no matching passage. A valid source ID confirms that the model saw the passage; it doesn't establish that every claim is supported.

In **09**, ask `How do I recharge the battery?`, then `How long does it last?` in the same session. Look for `Using remembered topic: battery`. Type `quit` to exit. A fresh session starts with no remembered topic.

## 10–15: Handle failures and coordinate work

| Example | What to watch for | Run |
| --- | --- | --- |
| [10 · Replanning](10_planning_and_replanning.py) | A blocked passage forces the agent to plan a new route from its current location. | `uv run python 10_planning_and_replanning.py` |
| [11 · Safe recovery](11_safe_recovery.py) | A timeout can happen before or after delivery. The agent checks the record and reuses the operation ID when retrying. | `uv run python 11_safe_recovery.py` |
| [12 · Resume after approval](12_checkpoints_and_resumable_approval.py) | Separate processes save, approve, and resume the same request. | Follow the checkpoint commands below. |
| [13 · Coordinated agents](13_coordinated_agents.py) | Route and battery specialists run independent checks. The coordinator combines their results. | `uv run python 13_coordinated_agents.py` |
| [14 · MCP tools](14_mcp_agent.py) | The agent launches the [server](14_robot_mcp_server.py), discovers a tool, and uses its battery reading to make a decision. | `uv run python 14_mcp_agent.py --robot robot-1` |
| [15 · Evaluation and observability](15_evaluation_and_observability.py) | A trace shows what happened. Fixed expectations reveal whether a rule change broke a decision. | `uv run python 15_evaluation_and_observability.py` |

For **12**, use a fresh checkpoint in a temporary directory. Type `yes` at the approval prompt:

```bash
checkpoint_dir="$(mktemp -d)"
checkpoint="$checkpoint_dir/delivery.json"
uv run python 12_checkpoints_and_resumable_approval.py start --checkpoint "$checkpoint"
uv run python 12_checkpoints_and_resumable_approval.py resume --checkpoint "$checkpoint"
uv run python 12_checkpoints_and_resumable_approval.py approve --checkpoint "$checkpoint"
uv run python 12_checkpoints_and_resumable_approval.py resume --checkpoint "$checkpoint"
uv run python 12_checkpoints_and_resumable_approval.py resume --checkpoint "$checkpoint"
```

The first resume is blocked. After approval, the next resume records the simulated delivery, and the last reports that it was already delivered.

For **14**, try `--robot robot-2` for a higher battery reading or `--robot unknown` for a tool error. The client starts the server for you.

For **15**, the default run passes all four cases. Try a change that looks harmless:

```bash
uv run python 15_evaluation_and_observability.py --threshold 10
```

Expect **3 of 4 cases to pass** and exit code **1**. The trace shows why: the agent now tells the robot with 15% battery to move, while the evaluation still expects it to recharge.

These are teaching examples. They show how the pieces work in isolation. Production behavior such as concurrent workers, recovery around external side effects, and deployment belongs to [Phase 2](../../production/README.md).
