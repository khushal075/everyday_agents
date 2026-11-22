# Architecture decision records

An ADR explains a design decision, the constraint behind it, and the trade-offs
it creates. Read the [walkthrough](../request-walkthrough.md) for what happens,
then use these records to ask why the system is shaped this way.

These records document the current implementation on 22 November 2026. They
are a retrospective explanation of the code, not historical meeting minutes.
“Accepted” means the choice is used by this local reference implementation.

| Record | Decision |
| --- | --- |
| [0001](0001-separate-agent-responsibilities.md) | Separate prediction, policy, execution, and verification. |
| [0002](0002-single-host-sqlite-runtime.md) | Use a single-host SQLite runtime for the learning reference. |
| [0003](0003-persist-exact-approved-proposals.md) | Persist exact proposals and evidence before approval and resume. |

For a new decision, describe its context, decision, consequences, alternatives,
and implementation evidence. Record the actual trade-off rather than claiming
one choice is universally best. Add a superseding record if a decision changes.
