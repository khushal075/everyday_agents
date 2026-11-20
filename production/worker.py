"""
Claim and process one feedback job from the SQLite queue.
"""

import os
import sys
from pathlib import Path
from everyday_agents.agents.sentiment.agent import create_agent
from production.category_03_reliability_and_access.recovery import RecoveryPolicy
from production.category_03_reliability_and_access.approvals import (
    ActionRequest, ApprovalPolicy, ApprovalRequired, ApprovalStore,
)
from production.category_03_reliability_and_access.security import (
    AccessDenied, AccessPolicy, Principal,
)
from production.store import FeedbackStore, JobClaim, LeaseLost


class FeedbackWorker:
    """
    Run the sentiment agent for a queued job and save the outcome.
    """
    def __init__(
        self, store: FeedbackStore, *,
        tool_permissions: frozenset[str] = frozenset({"execute:record", "execute:prepare_review"}),
    ):
        self.store = store
        self.tool_permissions = tool_permissions
        self.approvals = ApprovalStore(store.database_path)
        self.agent = create_agent()
        self.recovery = RecoveryPolicy(
            max_attempts=3,
            initial_delay_seconds=1.0,
            max_delay_seconds=30.0,
        )

    def run_once(self) -> int:
        """
        Claim one eligible job and save its outcome.
        """
        claim = self.store.claim_next(max_attempts=self.recovery.max_attempts)
        if claim is None:
            print("No eligible jobs.")
            return 0

        print(f"Claimed job {claim.job.job_id}, attempt {claim.attempt}", flush=True)

        try:
            return self._process(claim)
        except LeaseLost as error:
            print(f"Lease lost for job {claim.job.job_id}: {error}")
            return 1

    def _process(self, claim: JobClaim) -> int:
        """
        Run the agent and save the result using the workers claim.
        """
        job = claim.job

        try:
            prediction = self.agent.predictor.predict(job.feedback_text)
            decision = self.agent.policy.decide(prediction)
        except Exception as error:
            return self._fail_job(
                claim=claim,
                error=f"{type(error).__name__}: {error}",
                retryable=isinstance(error, (TimeoutError, ConnectionError)),
            )

        action = decision.action
        if action not in ("record", "prepare_review"):
            return self._fail_job(claim, f"Unsupported action: {action!r}")
        if decision.parameters:
            return self._fail_job(claim, "Feedback actions do not accept parameters.")

        access = AccessPolicy()
        principal = Principal("feedback-worker", job.tenant_id, self.tool_permissions)
        try:
            access.require(
                principal, resource_tenant_id=job.tenant_id, permission=f"execute:{action}",
            )
            proposal = self.approvals.get_request(f"{job.job_id}:review", job.tenant_id)
            if job.approval_required and (action == "prepare_review" or proposal is not None):
                request = ActionRequest.create(
                    operation_id=f"{job.job_id}:review",
                    tenant_id=job.tenant_id,
                    action=action,
                    parameters={"feedback": job.feedback_text, "reason": decision.reason},
                )
                approval = self.approvals.get_decision(request.operation_id, job.tenant_id)
                if approval is None:
                    self.store.await_approval(claim, action, decision.reason)
                    print(f"Job {job.job_id} is awaiting approval.")
                    return 0
                ApprovalPolicy(access).require(request, approval)
            self.store.complete(
                job_id=job.job_id,
                action=action,
                reason=decision.reason,
                claim_token=claim.token,
            )
        except (ApprovalRequired, AccessDenied) as error:
            return self._fail_job(claim, str(error))

        print(f"Completed job {job.job_id} with action {action}")
        return 0

    def _fail_job(
        self, claim: JobClaim, error: str, *, retryable: bool = False,
    ) -> int:
        """Schedule a retry or persist an escalated failure."""
        decision = self.recovery.decide(
            claim.attempt, retryable=retryable, cancelled=False,
        )
        if decision.action == "retry":
            self.store.schedule_retry(
                claim=claim, error=error, delay_seconds=decision.delay_seconds,
            )
            print(
                f"Job {claim.job.job_id} scheduled for retry "
                f"in {decision.delay_seconds} seconds."
            )
            return 1

        self.store.fail(
            job_id=claim.job.job_id,
            error=error,
            claim_token=claim.token,
            reason=f"Escalated: {decision.reason}",
        )
        print(f"Job {claim.job.job_id} escalated: {decision.reason}")
        return 1


def main() -> int:
    """
    Connect to the same database as the feedback API
    """
    database_path = Path(
        os.environ.get("FEEDBACK_DB_PATH", "feedback-runtime.sqlite3")
    )
    return FeedbackWorker(FeedbackStore(database_path)).run_once()

if __name__ == "__main__":
    raise SystemExit(main())
