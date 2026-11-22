# ADR 0003 · Persist exact approved proposals

- Status: Accepted for the local reference.
- Documented: 22 November 2026.

## Context

A person may approve work after the original worker exits. The model, retrieved
policy, or generated reason could differ if recomputed later. Approval must bind
the action that was actually presented, and a retry must not silently replace it.

## Decision

Save an immutable ActionRequest with a stable operation ID, tenant, action, and
serialized parameters before waiting for approval. Policy parameters include
feedback, route, reason, citation, and a full evidence snapshot. Persist the
approval decision against that exact request.

Policy resume validates and restores the saved proposal without retrieval or
inference. Execution rechecks the lease, cancellation, saved request, and required
approval in the transaction that inserts the review and completes the job.

## Consequences

Resume works without the original model or policy file, and the executed action
can be compared with what was approved. Stored proposals contain customer text
and evidence, so a real deployment needs appropriate access and retention policies.

Approval does not refresh stale business facts or prove that the original model
recommendation was correct. Changed action details need a new operation/proposal;
this reference uses a new job for a new proposal. External actions still need
their own idempotency and reconciliation behavior.

## Alternative

Saving only an “approved” flag and recomputing a recommendation on resume would
use less stored context, but could authorize different action details. Keeping
only process memory would lose the proposal when the worker exits.

## Evidence

- [Proposal preparation and restoration](../../production/feedback_workflow.py)
- [Approval records and checks](../../production/category_03_reliability_and_access/approvals.py)
- [Transactional policy execution](../../production/store.py)
- [Restart, approval, and tampering checks](../../tests/integration/test_feedback_workflow.py)
