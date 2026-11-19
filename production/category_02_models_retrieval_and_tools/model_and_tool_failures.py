"""
Exercise policy routing and verify that failure create no review items.
"""

import json
from pathlib import Path
from typing import Literal

from production.category_02_models_retrieval_and_tools import context
from production.category_02_models_retrieval_and_tools.context import ContextBuilder, ModelContext
from production.category_02_models_retrieval_and_tools.models import (
    GenerateRecommendation,
    InvalidModelResponse,
    RoutingModel
)

from production.category_02_models_retrieval_and_tools.retrieval import PolicyRetriever
from production.category_02_models_retrieval_and_tools.tools import ReviewTool, ToolRejected

POLICY_PATH = Path(__file__).resolve().parent / "fixtures" / "support_policy.md"
DUPLICATE_CHARGE = "I was charged twice for my subscriptions"

RoutingOutcome = Literal[
    "review_created",
    "no_policy_match",
    "model_timeout",
    "invalid_model_response",
    "tool_rejected",
    "verification_failed",
]

class PolicyRoutingWorkflow:
    """
    Retrieve policy evidence, ask the model, and verify the tool result.
    """

    def __init__(
            self,
            retriever: PolicyRetriever,
            builder: ContextBuilder,
            model: RoutingModel,
            tool: ReviewTool
    ):
        self.retriever = retriever
        self.builder = builder
        self.model = model
        self.tool = tool

    def run(self, feedback: str) -> RoutingOutcome:
        """
        Run one feedback request and return its outcome.
        """
        matches = self.retriever.search(feedback)
        context = self.builder.build(feedback, matches)

        try:
            recommendation = self.model.recommend(context)
        except TimeoutError:
            return "model_timeout"
        except InvalidModelResponse:
            return "invalid_model_response"

        if recommendation is None:
            return "no_policy_match"

        try:
            record = self.tool.execute(context.feedback, recommendation)
        except ToolRejected:
            return "tool_rejected"

        if self.tool.verify(record):
            return "review_created"

        return "verification_failed"


def billing_response(context: ModelContext) -> str:
    """Simulate a model recommending billing review with a valid citation"""
    passage = context.evidence[0]
    return json.dumps({
        "route": "billing_review",
        "reason": "The customer reports being charged twice.",
        "source": passage.source,
        "heading": passage.heading,
    })

def response_with_unknown_citation(context: ModelContext) -> str:
    """
    Simulate a model citing a policy section outside its context.
    :param context:
    :return:
    """
    response = json.loads(billing_response(context))
    response["heading"] = "Warranty coverage"
    return json.dumps(response)

def response_with_wrong_route(context: ModelContext) -> str:
    """Simulate a valid citation paired with a disallowed route."""
    response = json.loads(billing_response(context))
    response["route"] = "account_support"
    return json.dumps(response)


def timeout_response(_context: ModelContext) -> str:
    """
    Simulate a timeout raised by the model adapter.
    """
    raise TimeoutError("Model did not respond in time")


def unexpected_model_call(_context: ModelContext) -> str:
    """
    Fail the exercise if the model is called with empty evidence.
    """
    raise AssertionError("The model was called without evidence")


def main():
    retriever = PolicyRetriever(POLICY_PATH)
    builder = ContextBuilder()

    cases: tuple[tuple[str, str, GenerateRecommendation, RoutingOutcome, int], ...] = (
        ("Duplicate charge", DUPLICATE_CHARGE, billing_response, "review_created", 1),
        ("No policy match", "Can you add dark mode?", unexpected_model_call, "no_policy_match", 0),
        ("Model timeout", DUPLICATE_CHARGE, timeout_response, "model_timeout",0),
        ("Unknown citation",DUPLICATE_CHARGE,response_with_unknown_citation, "invalid_model_response",0),
        ("Disallowed route", DUPLICATE_CHARGE, response_with_wrong_route, "tool_rejected", 0)
    )

    for name, feedback, generate, expected_outcome, expected_count in cases:
        tool = ReviewTool()
        workflow = PolicyRoutingWorkflow(
            retriever=retriever,
            builder=builder,
            model=RoutingModel(generate),
            tool=tool
        )

        outcome = workflow.run(feedback)
        review_count = len(tool.records)

        if (outcome, review_count) != (expected_outcome, expected_count):
            raise AssertionError(
                f"{name}: Expected {expected_count} outcome, got {review_count} reviews.",
                f"review items, got {outcome}, with {review_count}"
            )

        print(f"PASS | {name} | {outcome} | review_count: {review_count}")

if __name__ == "__main__":
    """
    Commands to run:
        - uv run python -m production.category_02_models_retrieval_and_tools.model_and_tool_failures
    """
    main()
