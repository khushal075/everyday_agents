"""
Claim and process one feedback job from the SQLite queue.
"""

import os
from contextlib import AbstractContextManager
from pathlib import Path
from time import perf_counter
from everyday_agents.agents.sentiment.agent import create_agent
from production.category_03_reliability_and_access.recovery import RecoveryPolicy
from production.category_03_reliability_and_access.approvals import (
    ActionRequest, ApprovalPolicy, ApprovalRequired, ApprovalStore,
)
from production.category_03_reliability_and_access.security import (
    AccessDenied, AccessPolicy, Principal,
)
from production.category_04_evaluation_and_observability.telemetry import EventOutcome
from production.store import FeedbackStore, JobClaim, LeaseLost
from production.feedback_workflow import FeedbackWorkflow
from production.category_02_models_retrieval_and_tools.models import configured_routing_model
from production.category_02_models_retrieval_and_tools.retrieval import PolicyRetriever
from production.category_02_models_retrieval_and_tools.tools import PersistentReviewTool


class FeedbackWorker:
    """
    Run the sentiment agent for a queued job and save the outcome.
    """
    def __init__(
        self, store: FeedbackStore, *,
        workflow: FeedbackWorkflow | None = None,
        tool_permissions: frozenset[str] = frozenset({"execute:record", "execute:prepare_review"}),
    ):
        self.store = store
        self.workflow = workflow
        self.review_tool = PersistentReviewTool(store)
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
            self._event("worker.lease_lost", claim, perf_counter(), outcome="failed")
            print(f"Lease lost for job {claim.job.job_id}: {error}")
            return 1

    def _process(self, claim: JobClaim) -> int:
        """
        Run the agent and save the result using the workers claim.
        """
        started = perf_counter()
        job = claim.job
        if job.workflow_mode == "policy":
            return self._process_policy(claim)

        try:
            with self._measure("worker.prediction", claim):
                prediction = self.agent.predictor.predict(job.feedback_text)
            with self._measure("worker.decision", claim):
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
            with self._measure("worker.permission", claim):
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
                    self._event("worker.awaiting_approval", claim, started)
                    print(f"Job {job.job_id} is awaiting approval.")
                    return 0
                with self._measure("worker.approval", claim):
                    ApprovalPolicy(access).require(request, approval)
            with self._measure("worker.execution", claim):
                self.store.complete(
                    job_id=job.job_id,
                    action=action,
                    reason=decision.reason,
                    claim_token=claim.token,
                )
        except (ApprovalRequired, AccessDenied) as error:
            return self._fail_job(claim, str(error))

        self._event("worker.completed", claim, started)
        print(f"Completed job {job.job_id} with action {action}")
        return 0

    def _process_policy(self, claim: JobClaim) -> int:
        """
        - Restore a saved proposal or retrieve evidence and prepare it once.
        - Enforce permissions before saving, approving, or executing an action.
        - Reuse the exact proposal after approval, retry, or worker restart.

        :param claim: Tenant-owned policy job and its active lease.
        :return: Zero on completion or approval wait; one on failure or retry.
        """
        started = perf_counter()
        job = claim.job
        completed = False
        try:
            saved = self.approvals.get_request(f"{job.job_id}:review", job.tenant_id)
            if saved is not None:
                with self._measure("worker.proposal_restored", claim):
                    plan = FeedbackWorkflow.restore(
                        saved, feedback=job.feedback_text, job_id=job.job_id, tenant_id=job.tenant_id,
                    )
            else:
                with self._measure("worker.policy_preparation", claim):
                    if self.workflow is None:
                        policy_path = Path(os.environ.get("FEEDBACK_POLICY_PATH", str(
                            Path(__file__).resolve().parent / "category_02_models_retrieval_and_tools/fixtures/support_policy.md"
                        )))
                        self.workflow = FeedbackWorkflow(PolicyRetriever(policy_path), configured_routing_model())
                    plan = self.workflow.prepare(job.feedback_text, job_id=job.job_id, tenant_id=job.tenant_id)
            action = "prepare_review" if plan.request is not None else "record"
            with self._measure("worker.permission", claim):
                AccessPolicy().require(
                    Principal("feedback-worker", job.tenant_id, self.tool_permissions),
                    resource_tenant_id=job.tenant_id, permission=f"execute:{action}",
                )
            if plan.request is None:
                # No evidence is an explicit no-review outcome, not a model guess.
                with self._measure("worker.execution", claim):
                    self.store.complete(job.job_id, "record", "No matching policy evidence; no review created.", claim_token=claim.token)
                self._event("worker.no_policy_match", claim, started)
            else:
                if self.store.save_policy_request(claim, plan.request):
                    self._event("worker.awaiting_approval", claim, started)
                    print(f"Job {job.job_id} is awaiting approval.")
                    return 0
                if job.approval_required:
                    with self._measure("worker.approval", claim):
                        ApprovalPolicy(AccessPolicy()).require(plan.request, self.approvals.get_decision(
                            plan.request.operation_id, job.tenant_id,
                        ))
                with self._measure("worker.execution", claim):
                    record = self.review_tool.execute(claim, plan.request)
                completed = True
                with self._measure("worker.verification", claim):
                    if not self.review_tool.verify(claim, plan.request, record):
                        raise RuntimeError("Persistent review verification failed.")
        except LeaseLost:
            raise
        except Exception as error:
            current = self.store.get_job(job.job_id, job.tenant_id)
            if completed or (current is not None and current.status == "completed"):
                # Execution already committed. Do not retry the business action.
                self._event("worker.verification_failed", claim, started, outcome="failed")
                print(f"Job {job.job_id} committed but verification failed: {type(error).__name__}")
                return 1
            return self._fail_job(claim, f"{type(error).__name__}: {error}", retryable=isinstance(error, (TimeoutError, ConnectionError)))
        self._event("worker.completed", claim, started)
        print(f"Completed policy job {job.job_id} with action {action}")
        return 0

    def _fail_job(
        self, claim: JobClaim, error: str, *, retryable: bool = False,
    ) -> int:
        """Schedule a retry or persist an escalated failure."""
        started = perf_counter()
        decision = self.recovery.decide(
            claim.attempt, retryable=retryable, cancelled=False,
        )
        if decision.action == "retry":
            self.store.schedule_retry(
                claim=claim, error=error, delay_seconds=decision.delay_seconds,
            )
            self._event("worker.retry_scheduled", claim, started, outcome="failed")
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
        self._event("worker.escalated", claim, started, outcome="failed")
        print(f"Job {claim.job.job_id} escalated: {decision.reason}")
        return 1

    def _measure(self, stage: str, claim: JobClaim) -> AbstractContextManager[None]:
        """
        - Measure one worker stage using the persistent job as its run ID.
        - Include tenant and attempt information in every stage event.
        """
        return self.store.telemetry.measure(
            run_id=claim.job.job_id, job_id=claim.job.job_id,
            tenant_id=claim.job.tenant_id, attempt=claim.attempt, stage=stage,
        )

    def _event(
        self, stage: str, claim: JobClaim, started: float, *, outcome: EventOutcome = "passed",
    ) -> None:
        """
        - Record a worker outcome after its state transition commits.
        - Keep telemetry failures from changing the job outcome.
        """
        self.store.telemetry.safe_emit(
            run_id=claim.job.job_id, job_id=claim.job.job_id,
            tenant_id=claim.job.tenant_id, attempt=claim.attempt,
            stage=stage, outcome=outcome,
            duration_ms=(perf_counter() - started) * 1000,
        )


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
