# 02 · Models, retrieval, and tools

A customer says they were charged twice. This exercise retrieves the relevant
support policy, builds context, validates a routing recommendation, and creates
a review item only when the cited section permits the proposed route.

## Follow the request

1. Search policy sections by keyword overlap.
2. Select complete passages within an evidence character budget.
3. Ask the configured generator for a JSON recommendation.
4. Check the route, reason, and citation against the supplied evidence.
5. Check that the cited policy section permits the route.
6. Create a review item and verify it against the tool's saved records.

An empty evidence list returns `no_policy_match` before calling the generator.

## Files

| File | Responsibility |
| --- | --- |
| `fixtures/support_policy.md` | Fictional policies for duplicate charges, refunds, and account access. |
| `retrieval.py` | Load Markdown sections and rank exact keyword matches. |
| `context.py` | Preserve feedback and select bounded policy evidence. |
| `models.py` | Validate the generator's JSON recommendation and citation. |
| `tools.py` | Apply the allowed-route mapping and create and verify local review items. |
| `search_support_policy.py` | Show a matching policy and a request with no match. |
| `model_and_tool_failures.py` | Run the workflow with reproducible model responses and failures. |

## Run

From the repository root, use Python 3.12 or newer and the project environment.

```bash
uv sync --locked
uv run python -m production.category_02_models_retrieval_and_tools.search_support_policy
uv run python -m production.category_02_models_retrieval_and_tools.model_and_tool_failures
```

The search returns the duplicate-charge section for “I was charged twice for
my subscription.” It prints the source and matching words. The dark-mode
request produces an empty result.

The workflow exercise checks these outcomes and exits with an error if an
expectation fails.

| Scenario | Outcome | Review items |
| --- | --- | --- |
| Duplicate charge | `review_created` | 1 |
| No matching policy | `no_policy_match` | 0 |
| Simulated model timeout | `model_timeout` | 0 |
| Citation outside the context | `invalid_model_response` | 0 |
| Route disallowed by the cited policy | `tool_rejected` | 0 |

## Current boundaries

The generator uses scripted responses, and the timeout is injected by raising
an exception. Review records live in memory for one tool instance. The workflow
runs independently of Category 01's API, worker, and SQLite store.

Search uses exact words and can miss paraphrases or retrieve irrelevant text
with overlapping words. The evidence budget counts characters in the selected
source, heading, and passage. Feedback is preserved in full.

Citation validation checks that the cited section was supplied to the model.
The tool checks a configured source-and-heading mapping. These checks establish
which section and route were used. Assessing whether the explanation is
supported by the passage requires additional evaluation.

Real model inference, external tool calls, persistent review creation, and
worker integration remain future exercises.
