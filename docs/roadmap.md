# Roadmap

## Preserved milestone: v0.1.0

The annotated Git tag preserves the original sentiment-focused release and its
original scaffolding. Current working code retains the sentiment baseline,
trained predictor, policy, tool, training/evaluation, artifact loading, CLI, and
local tests. The shared core and ML utilities remain available.

Generated artifacts and build outputs remain local and ignored by Git. They are
not course content or evidence of additional completed use cases.

## Completed: concepts-first learning path

The 15 examples in `examples/concepts/` are implemented, with commands, expected
behavior, dependencies, and explicit boundaries in their README. Examples 07–09
need a local Ollama model. Example 14 uses a companion MCP server.

See [learning path](learning-path.md) and [coverage matrix](coverage-matrix.md).

## Completed: Phase 2 local reference

The five production categories are implemented. Policy retrieval and optional
Ollama inference now connect to persistent jobs, immutable proposals, exact-action
approval, resumable workers, transactional review creation, and result verification.
The original sentiment workflow remains available and existing jobs keep their mode.

Verification on 22 November 2026 includes 153 software tests, a package build,
standalone restart/crash scenarios, and both sentiment and policy container smoke
checks. Model protocol tests use local HTTP fixtures; live Ollama inference and
hosted identity/notification endpoints need environment-specific validation.

## Optional extensions after Phase 2

Choose these for a concrete deployment or domain requirement:

- Connect a real business API with idempotency and reconciliation contracts.
- Evaluate retrieval and model recommendations on representative held-out tasks.
- Introduce tenant-specific policy ingestion, source access, freshness, and retention.
- Add production monitoring destinations, dashboards, alert scheduling, and TLS.
- Replace single-host SQLite when distributed capacity and availability require it.

These are beyond the completed local reference scope. They are not prerequisites
for running either learning phase.

## Future domain applications

These remain candidates rather than implemented packages:

| Domain | Candidate workflow |
| --- | --- |
| Photo cleanup | Quality and duplicate analysis, reviewable cleanup proposals |
| Job matching | Skills/preferences matching and explained shortlists |
| Expense organiser | Categories, unusual transactions, uncertain-entry review |
| Study coach | Mastery estimation and next-exercise selection |
| Task priority | Ranking and daily plans constrained by available time |

Create their code, configuration, and dataset schemas only when the corresponding
implementation begins. They are optional domains for teaching concepts, not a
prerequisite for completing all operational exercises.
