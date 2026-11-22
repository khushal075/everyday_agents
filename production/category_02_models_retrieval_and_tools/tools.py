"""
Create and verify local review record for allowed policy routes.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from production.store import FeedbackStore, JobClaim, ReviewRecord as PersistentReviewRecord
    from production.category_03_reliability_and_access.approvals import ActionRequest
from uuid import uuid4

from production.category_02_models_retrieval_and_tools.models import ReviewRoute, RoutingRecommendation


ALLOWED_ROUTES: dict[tuple[str, str], ReviewRoute] = {
    ("support_policy.md", "duplicate charges"): "billing_review",
    ("support_policy.md", "refund requests"): "billing_review",
    ("support_policy.md", "account access"): "account_support",
}


@dataclass(frozen=True)
class ReviewRecord:
    """
    A local review item with a reference to the policy used.
    """
    review_id: str
    feedback: str
    route: ReviewRoute
    reason: str
    source: str
    heading: str


class ToolRejected(ValueError):
    """
    The requested action failed a tool input or policy check.
    """


class ReviewTool:
    """
    Apply a routing rule before creating a local review item.
    """
    def __init__(self):
        self._records: dict[str, ReviewRecord] = {}

    @property
    def records(self) -> tuple[ReviewRecord, ...]:
        """
        Return the review items created during this run.
        """
        return tuple(self._records.values())

    def execute(
            self,
            feedback: str,
            recommendation: RoutingRecommendation,
    ) -> ReviewRecord:
        """Created a review item when cited policy permits the route"""

        if not feedback.strip():
            raise ToolRejected("Feedback must contain text")

        policy_passage = recommendation.policy_passage
        policy_key = (policy_passage.source, policy_passage.heading.casefold())

        if ALLOWED_ROUTES.get(policy_key) != recommendation.route:
            raise ToolRejected("The cited policy does not permit the route.")

        record = ReviewRecord(
            review_id = uuid4().hex,
            feedback=feedback,
            route = recommendation.route,
            reason = recommendation.reason,
            source= policy_passage.source,
            heading= policy_passage.heading,
        )

        self._records[record.review_id] = record
        return record

    def verify(self, record: ReviewRecord) -> bool:
        """
        Confirm that the returned record matches what the tool saved.
        """
        return self._records.get(record.review_id) == record


class PersistentReviewTool:
    """
    - Execute a saved proposal through the lease-protected workflow store.
    - Verify the durable review against the exact proposed parameters.
    """

    def __init__(self, store: "FeedbackStore") -> None:
        """
        - Reuse the worker's store and telemetry connection settings.

        :param store: Persistent workflow store.
        """
        self.store = store

    def execute(self, claim: "JobClaim", request: "ActionRequest") -> "PersistentReviewRecord":
        """
        - Atomically complete the job and create its approved review.

        :param claim: Active worker lease.
        :param request: Exact saved proposal to execute.
        :return: The durable review read after commit.
        """
        self.store.complete_policy(claim, request)
        record = self.store.get_review(claim.job.job_id, claim.job.tenant_id)
        if record is None:
            raise RuntimeError("Committed policy review could not be read back.")
        return record

    def verify(self, claim: "JobClaim", request: "ActionRequest", record: "PersistentReviewRecord") -> bool:
        """
        - Compare the durable result with its operation, route, and citation.
        - Confirm job completion and ownership through tenant-scoped reads.

        :param claim: Job identity used for execution.
        :param request: Exact proposal used for execution.
        :param record: Result returned by the persistent tool.
        :return: True only when the durable result matches the proposal.
        """
        import json
        parameters = json.loads(request.parameters_json)
        job = self.store.get_job(claim.job.job_id, claim.job.tenant_id)
        return (
            job is not None and job.status == "completed" and job.action == request.action
            and job.reason == parameters["reason"]
            and record == self.store.get_review(claim.job.job_id, claim.job.tenant_id)
            and record.job_id == claim.job.job_id and record.operation_id == request.operation_id
            and record.route == parameters["route"] and record.source == parameters["source"]
            and record.heading == parameters["heading"] and record.reason == parameters["reason"]
        )
