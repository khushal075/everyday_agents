# Roadmap

## Preserved milestone: v0.1.0

The annotated Git tag preserves the original sentiment-focused release and its
original scaffolding. Current working code retains the sentiment baseline,
trained predictor, policy, tool, training/evaluation, artifact loading, CLI, and
local tests. The shared core and ML utilities remain available.

Generated artifacts and build outputs remain local and ignored by Git. They are
not course content or evidence of additional completed use cases.

## Next: concepts-first learning path

Create standalone examples one at a time under `examples/concepts/`. Agree the
scenario and teaching objective before implementation. Include a complete flow,
expected output, an actual failure boundary, checks, and an honest production
boundary. Do not create empty executable placeholders for future lessons.

See [learning path](learning-path.md) and [coverage matrix](coverage-matrix.md).
No concept implementations are included in the structural cleanup.

## Later: production behaviour

Build the integrated application and operational exercises under `production/`,
reusing the Python package for shared functionality. Implementation follows
Phase 1 and is not implied by the directory's name.

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
