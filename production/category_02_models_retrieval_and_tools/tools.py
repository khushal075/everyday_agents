"""
Create and verify local review record for allowed policy routes.
"""

from dataclasses import dataclass
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
