# How AI Agents Work: 33 Runnable Python Examples

What happens between giving an agent a task and hearing it say “done”? These examples walk through the steps: deciding what to do, finding information, using tools, asking for permission, and checking what actually happened.

Each script isolates one idea so you can run it, change it, and see the result. Together, they show the building blocks you can combine when designing an agent system.

Every example uses the same small world: a robot a few steps from its destination, with a battery that holds two units. Each one looks at a different part of the same agent, so you never have to learn a new scenario. No AI or machine-learning background is needed.

Start at **01** to build up from the basics, or jump to **11** for safe retries, **12** for approval across restarts, **15** to see an evaluation catch a regression, **16** to see a real model choose tools, **23** for memory that lasts between sessions, or **29** to run tool calls in parallel.

## Set up once

Use Python 3.12 or newer and [uv](https://docs.astral.sh/uv/). From the repository root:

```bash
uv sync --locked
cd examples/concepts
```

Run the commands below from this directory. The project environment includes scikit-learn for Example 02 and the MCP Python SDK for Example 14.

**Examples 07–09 need Ollama.** Examples 16–22, 24–27, 30 and 32 also run without it using `--scripted` (or `--toy`) fixtures. These demonstrate the control flow before you try a real model. Examples 23, 28, 29, 31 and 33 use plain code and need no model.

For the model runs, have Ollama running locally at `http://localhost:11434` and a text-generation model installed. If the server isn't already running, start it in another terminal:

```bash
ollama serve
```

Use `ollama list` to find the exact installed model name. In the commands below, `qwen` is a local alias; replace it with your installed model name if you haven't created that alias.

Example 16 needs a model that supports tool calling (check that `ollama show <model>` lists `tools`). Example 18 needs an embedding model (`ollama pull nomic-embed-text`). Example 22 needs a small and a large model, for example `qwen2.5:3b` and `qwen`.

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

## 16–22: Work with real models safely

Examples 01–15 mostly decide with plain code. These examples put a language model in charge of parts of the work, and show the code around it that keeps the robot safe.

| Example | What to watch for | Run |
| --- | --- | --- |
| [16 · Model-chosen tools](16_llm_tool_calling_loop.py) | The model requests tools; rejected calls go back to it so it can correct itself. When it says "done", the agent checks the robot before agreeing. | `uv run python 16_llm_tool_calling_loop.py --scripted recovers` |
| [17 · Structured output and repair](17_structured_output_and_repair.py) | The model returns a whole trip plan as JSON. Valid JSON can still be a wrong plan, so the plan is simulated, and every error goes back for a repair. | `uv run python 17_structured_output_and_repair.py --scripted repairs` |
| [18 · Search by meaning](18_embeddings_and_hybrid_retrieval.py) | Keyword search misses "refill its energy"; meaning-based search misses the code "E42". Combining both finds each one. | `uv run python 18_embeddings_and_hybrid_retrieval.py --toy` |
| [19 · Context budget](19_context_budget_and_summarization.py) | On a long trip the history keeps growing. Older events are summarized so each request stays under the limit, while the current state is always sent exactly. | `uv run python 19_context_budget_and_summarization.py --scripted` |
| [20 · Injected instructions](20_prompt_injection_guardrails.py) | A user note tells the model to disable a safety check. A scanner, labelled prompts, and a code rule each defend against it. | `uv run python 20_prompt_injection_guardrails.py --scripted obeys --no-scanner` |
| [21 · Grading with a judge](21_llm_as_judge_evaluation.py) | Exact match rejects a valid alternative plan; simulation does not. A judge grades the explanations, and is itself checked against human labels. | `uv run python 21_llm_as_judge_evaluation.py --scripted` |
| [22 · Routing and caching](22_model_routing_and_caching.py) | Each decision tries a cache, then a small model, then a large one only if needed. Compare the cost with always using the large model. | `uv run python 22_model_routing_and_caching.py --scripted` |

For **16**, also try `--scripted overconfident`: the model claims success two steps early, and the agent refuses to accept it. With a real model, run `--model qwen`. If the model writes tool calls as plain text instead of real tool calls, add `--parse-text-calls`; this is off by default because reading tool calls out of free text is risky.

For **17**, run `--model qwen --distance 7`. No valid plan exists within six actions, so watch what the model does: it keeps patching one error at a time and then repeats itself, and the agent stops with `no_progress`.

For **18**, try `--embed-model nomic-embed-text` and compare the results with the toy embedder. Real models give higher similarity scores to unrelated text, so the cut-off has to be tuned (`--min-similarity`).

For **19**, try `--budget 100` to see more of the history summarized, and `--budget 40` to see the run stop because even the essential facts do not fit.

For **20**, run without `--no-scanner` to see the note quarantined before it reaches the model. The scanner only matches known phrases, so a reworded attack would get through; the code rule that blocks unknown and impossible actions is the layer that does not depend on the model.

For **21**, run `--model qwen` to use a real judge, and compare its agreement score with the keyword judge's 4 of 5.

For **22**, notice that the small model's `recharge 1` is safe but not the best move, and it is cached anyway: validation checks that an answer is safe, not that it is the best one.

## 23–28: Run longer, larger tasks

These examples cover what changes when an agent works across sessions, splits work between helpers, runs code, or runs for a long time.

| Example | What to watch for | Run |
| --- | --- | --- |
| [23 · Long-term memory](23_long_term_memory.py) | Four simulated sessions reload one memory file. A correction replaces the old fact, an expired fact stops being recalled, and "forget" deletes a fact with its history. | `uv run python 23_long_term_memory.py demo` |
| [24 · Delegation and handoffs](24_dynamic_delegation_and_handoffs.py) | A planner splits the task and picks specialists; a made-up specialist is rejected. The battery specialist hands its work to the timing specialist, with what it found so far. | `uv run python 24_dynamic_delegation_and_handoffs.py --scripted` |
| [25 · Evaluate and improve](25_evaluator_optimizer_loop.py) | Each round is scored against three criteria and revised. A worse revision does not replace the best plan so far; the loop stops when every criterion is met. | `uv run python 25_evaluator_optimizer_loop.py --scripted` |
| [26 · Sandboxed execution](26_sandboxed_execution.py) | A generated script tries to read outside its folder, delete a file, and run a system command. Every line is checked first, so nothing runs. | `uv run python 26_sandboxed_execution.py --scripted unsafe` |
| [27 · Streaming and interruption](27_streaming_and_interruption.py) | Progress appears as it happens. A correction changes the destination mid-trip, and a cancel stops the robot between actions. | `uv run python 27_streaming_and_interruption.py --scripted` |
| [28 · Task-wide budgets](28_execution_wide_budgets.py) | Three deliveries share one budget for time, tool calls and cost. When it runs out, the agent stops between steps and still reports what was and was not done. | `uv run python 28_execution_wide_budgets.py --limits tools` |

For **23**, the demo uses a temporary file. To try memory yourself, run `remember dock-location "north wall"`, then `recall dock` in a new command, then `remember dock-location "east wall"` and `show` to see the old value kept as history. Memory here is different from the checkpoint in **12**: a checkpoint saves where one task stopped; memory saves knowledge for future tasks.

For **24**, try `--limit 4` to see the answer change to "No", and `--model qwen` to let a model plan the subtasks.

For **25**, try `--max-rounds 2`: the loop stops before the best plan appears and returns the long but valid plan from round 1, not the broken one from round 2.

For **26**, compare with `--scripted safe`, which runs and writes a trip log inside the sandbox folder. This example interprets a tiny command language on purpose: running generated Python with `exec()` cannot be made safe from inside Python. This is a restricted interpreter, not operating-system isolation. A preflight rejection runs no commands, but a later runtime failure may leave partial effects; there is no rollback.

For **27**, run `--interactive` and enter `further 2` to extend the destination while the trip runs. Enter `cancel` or press Ctrl+C during a step: the current action finishes, then the robot stops in a known state. With `--model qwen`, the plan description streams from the model as it is written.

For **28**, also try `--limits cost` and `--limits deadline`. Each step's assumed full price is checked before it starts, and one simulated model call is kept in reserve for the report. Time and cost are accounting simulations; the example does not enforce real request deadlines or provider spending limits.

## 29–33: Prepare for production

These examples cover what an agent needs once real users and real services are involved. None of them needs a model to run.

| Example | What to watch for | Run |
| --- | --- | --- |
| [29 · Parallel tool calls](29_parallel_tool_calls.py) | Three independent checks run at once: about 0.8s instead of 1.9s one after another. A failed optional check gives a warning; a failed required check stops the trip. | `uv run python 29_parallel_tool_calls.py` |
| [30 · Output guardrails](30_output_guardrails.py) | The reply is checked before the user sees it. A leaked key or email is removed; a false claim about the battery blocks the whole reply. | `uv run python 30_output_guardrails.py --scripted leaks_key` |
| [31 · Retry with backoff](31_retry_with_backoff.py) | A busy service returns 429 twice. The client waits about 1s, then 2s, then succeeds. A 400 is not retried at all. | `uv run python 31_retry_with_backoff.py --scenario busy` |
| [32 · Prompt versioning](32_prompt_versioning.py) | A reworded prompt scores higher but breaks a critical case, so it is not promoted. A further revision fixes that and is promoted. | `uv run python 32_prompt_versioning.py --candidate v2` |
| [33 · Agent to agent](33_agent_to_agent.py) | The robot reads another agent's card, sends it a task, answers its question, and gets a booking or a refusal. | `uv run python 33_agent_to_agent.py --scenario booked` |

For **29**, add `--sequential` to see the time add up, and try `--scenario door_timeout` and `--scenario route_fails`. Only checks that do not depend on each other can run in parallel.

For **30**, also try `--scripted leaks_email` and `--scripted wrong_fact`. With `--model qwen`, the model is asked to reveal a key that is in its instructions. Putting secrets in a prompt is the real mistake here; the guard is the last line of defence.

For **31**, try `--scenario retry_after` (the service says how long to wait) and `--scenario outage` (the client gives up after five attempts). The waits use a simulated clock, so the example runs instantly. Retrying is only safe when the request has no side effects or uses an operation ID, as in **11**.

For **32**, run `--candidate v3` to see a promotion. The script exits with code 1 when the candidate is rejected, so it can stop a release in CI. Add `--model qwen` to compare the prompts on a real model.

For **33**, try `--scenario dock_full` (the other agent says no) and `--scenario unknown_skill` (the robot does not send a task the other agent cannot do). The difference from **14**: an MCP tool does what it is told; another agent has its own rules, can ask questions, and can refuse. Protocols such as A2A carry these messages over HTTP.

## Which example covers what

| Concept | Examples |
| --- | --- |
| Deciding: rules, learned decisions, plans | 01, 02, 10, 17 |
| Tools: definitions, validated arguments, model-chosen tools, MCP, parallel calls | 03, 14, 16, 29 |
| Safety: permissions, approval, injected instructions, sandboxing, output checks | 04, 12, 20, 26, 30 |
| Checking results: verify effects, distrust "done", simulate plans | 05, 16, 17 |
| Finding information: keyword search, RAG, reranking, search by meaning | 06, 07, 08, 18 |
| Memory: within a session, context limits, across sessions | 09, 19, 23 |
| Failures: retries, recovery, repair loops, stopping when stuck, backoff | 11, 16, 17, 31 |
| Several agents: fixed specialists, delegation and handoffs, agent to agent | 13, 24, 33 |
| Measuring quality: evaluations, traces, judges, prompt versions | 15, 21, 32 |
| Improving quality: generate, critique, revise | 25 |
| Cost and speed: model routing, caching, task-wide budgets | 22, 28 |
| Long-running work: streaming, corrections, safe cancellation | 27 |

These are teaching examples. They show how the pieces work in isolation. Production behavior such as concurrent workers, recovery around external side effects, and deployment belongs to [Phase 2](../../production/README.md).
