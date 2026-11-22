"""
Prepare policy-grounded actions for the persistent feedback worker.

- Retrieve policy passages and build bounded model context.
- Validate the model recommendation and the policy's permitted route.
- Capture the proposed action and its evidence for persistence and approval.
- Leave permissions, approval checks, execution, and verification to the worker.

This module performs no review writes. The worker must persist the proposal
before waiting for approval and reuse that exact proposal when it resumes.
Saved proposals can be restored without calling retrieval or inference again.
"""

import json
from dataclasses import asdict, dataclass
from typing import Literal

from production.category_02_models_retrieval_and_tools.context import (
    ContextBuilder,
    ModelContext,
)
from production.category_02_models_retrieval_and_tools.models import (
    InvalidModelResponse,
    RoutingModel,
    RoutingRecommendation,
)
from production.category_02_models_retrieval_and_tools.retrieval import PolicyPassage, PolicyRetriever
from production.category_02_models_retrieval_and_tools.tools import (
    ALLOWED_ROUTES,
    ToolRejected,
)
from production.category_03_reliability_and_access.approvals import ActionRequest


@dataclass(frozen=True)
class FeedbackPlan:
    """
    - Describe one prepared review proposal or an absence of usable evidence.
    - Keep the selected context and recommendation available to the caller.
    - Represent no evidence explicitly, without inventing a successful action.

    :param context: Feedback and the exact policy passages sent to the model.
    :param recommendation: Validated recommendation, or None without evidence.
    :param request: Exact action proposal, or None without a recommendation.
    """

    context: ModelContext
    recommendation: RoutingRecommendation | None
    request: ActionRequest | None

    def __post_init__(self) -> None:
        """
        - Reject a partially populated plan.
        - Require evidence whenever a review is proposed.

        :return: None.
        """
        if (self.recommendation is None) != (self.request is None):
            raise ValueError("A recommendation and action request must appear together.")
        if self.recommendation is not None and not self.context.evidence:
            raise ValueError("A review proposal requires policy evidence.")

    @property
    def outcome(self) -> Literal["review_proposed", "no_policy_match"]:
        """
        - Report preparation status without claiming execution succeeded.

        :return: Whether a review was proposed or no usable evidence was found.
        """
        return "review_proposed" if self.request is not None else "no_policy_match"


class FeedbackWorkflow:
    """
    - Coordinate retrieval, context construction, and recommendation validation.
    - Produce a proposal without executing tools or granting authorization.
    - Accept an injected model so callers can use a real adapter or test fixture.
    """

    def __init__(
        self,
        retriever: PolicyRetriever,
        model: RoutingModel,
        *,
        builder: ContextBuilder | None = None,
        search_limit: int = 2,
    ) -> None:
        """
        - Store collaborators without loading a default model or policy file.

        :param retriever: Retriever for the policy available to this workflow.
        :param model: Adapter that generates and validates routing recommendations.
        :param builder: Optional context builder with explicit evidence limits.
        :param search_limit: Maximum number of retrieved candidate passages.
        :return: None.
        """
        if search_limit < 1:
            raise ValueError("search_limit must be at least 1.")
        self.retriever = retriever
        self.model = model
        self.builder = builder if builder is not None else ContextBuilder()
        self.search_limit = search_limit

    def prepare(
        self,
        feedback: str,
        *,
        job_id: str,
        tenant_id: str,
    ) -> FeedbackPlan:
        """
        - Retrieve evidence and ask the model only when usable context exists.
        - Reject a route that the cited policy does not permit.
        - Bind feedback, route, reason, and evidence to one stable operation ID.
        - Propagate model and retrieval failures for the worker's recovery policy.

        :param feedback: Original customer feedback, preserved in the proposal.
        :param job_id: Persistent job ID supplied by the worker's claimed job.
        :param tenant_id: Verified tenant ownership from that claimed job.
        :return: A validated proposal or an explicit no-policy-match plan.
        :raises ValueError: Feedback, job ID, or tenant ID is blank.
        :raises InvalidModelResponse: The model returns an invalid recommendation.
        :raises ToolRejected: The cited policy does not permit the proposed route.
        """
        if not feedback.strip() or not job_id.strip() or not tenant_id.strip():
            raise ValueError("Feedback, job_id, and tenant_id must not be blank.")

        matches = self.retriever.search(feedback, limit=self.search_limit)
        context = self.builder.build(feedback, matches)
        if not context.evidence:
            return FeedbackPlan(context, None, None)

        recommendation = self.model.recommend(context)
        if recommendation is None:
            raise InvalidModelResponse("No recommendation returned for available evidence.")

        passage = recommendation.policy_passage
        if passage not in context.evidence:
            raise InvalidModelResponse("The cited policy was not in the model context.")
        policy_key = (passage.source, passage.heading.casefold())
        if ALLOWED_ROUTES.get(policy_key) != recommendation.route:
            raise ToolRejected("The cited policy does not permit the route.")

        # ActionRequest accepts scalar values. Store the full evidence snapshot
        # as a canonical JSON string so approval also binds its exact contents.
        evidence_json = json.dumps(
            [asdict(item) for item in context.evidence],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        request = ActionRequest.create(
            operation_id=f"{job_id}:review",
            tenant_id=tenant_id,
            action="prepare_review",
            parameters={
                "feedback": context.feedback,
                "route": recommendation.route,
                "reason": recommendation.reason,
                "source": passage.source,
                "heading": passage.heading,
                "evidence_json": evidence_json,
            },
        )
        return FeedbackPlan(context, recommendation, request)

    @staticmethod
    def restore(request: ActionRequest, *, feedback: str, job_id: str, tenant_id: str) -> FeedbackPlan:
        """
        - Validate and reconstruct an immutable saved proposal without inference.
        - Reject changed job ownership, parameters, evidence, or policy permissions.

        :param request: Proposal loaded from persistent storage.
        :param feedback: Original feedback from the claimed job.
        :param job_id: Claimed job identifier.
        :param tenant_id: Claimed job owner.
        :return: The validated saved plan.
        :raises ValueError: The saved proposal is invalid for this job.
        """
        if (request.operation_id, request.tenant_id, request.action) != (
            f"{job_id}:review", tenant_id, "prepare_review",
        ):
            raise ValueError("Proposal does not belong to this job and tenant.")
        try:
            parameters = json.loads(request.parameters_json)
            expected = {"feedback", "route", "reason", "source", "heading", "evidence_json"}
            if not isinstance(parameters, dict) or set(parameters) != expected:
                raise ValueError("Unexpected proposal parameters.")
            if not all(isinstance(value, str) and value.strip() for value in parameters.values()):
                raise ValueError("Proposal parameters must be nonempty strings.")
            if parameters["feedback"] != feedback:
                raise ValueError("Proposal feedback differs from the saved job.")
            raw_evidence = json.loads(parameters["evidence_json"])
            if not isinstance(raw_evidence, list) or not raw_evidence:
                raise ValueError("Proposal requires policy evidence.")
            passages = []
            for item in raw_evidence:
                if not isinstance(item, dict) or set(item) != {"source", "heading", "text"}:
                    raise ValueError("Invalid policy evidence shape.")
                if not all(isinstance(value, str) and value.strip() for value in item.values()):
                    raise ValueError("Policy evidence must contain text.")
                passages.append(PolicyPassage(**item))
            context = ModelContext(feedback, tuple(passages))
            response = json.dumps({key: parameters[key] for key in ("route", "reason", "source", "heading")})
            recommendation = RoutingModel(lambda _: response).recommend(context)
            if recommendation is None:
                raise ValueError("Saved proposal has no recommendation.")
            passage = recommendation.policy_passage
            if ALLOWED_ROUTES.get((passage.source, passage.heading.casefold())) != recommendation.route:
                raise ToolRejected("The cited policy does not permit the saved route.")
            return FeedbackPlan(context, recommendation, request)
        except (TypeError, KeyError, json.JSONDecodeError) as error:
            raise ValueError("Invalid saved routing proposal.") from error
