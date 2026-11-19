"""
Validating routing recommendations against the evidence sent to the model.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Dict, Optional

from production.category_02_models_retrieval_and_tools.context import ModelContext
from production.category_02_models_retrieval_and_tools.retrieval import PolicyPassage

ReviewRoute = Literal["billing_review", "account_support"]
GenerateRecommendation = Callable[[ModelContext], str]

@dataclass(frozen=True)
class RoutingRecommendation:
    """
    A proposed route, its explanation, and the cited policy passage.
    """
    route: ReviewRoute
    reason: str
    policy_passage: PolicyPassage


class InvalidModelResponse(ValueError):
    """
    The model returned an invalid route, reason or cited.
    """

class RoutingModel:
    """
    Call a model and validate its response before passing it to a tool.
    """

    def __init__(self, generate: GenerateRecommendation) -> None:
        self.generate = generate

    def recommend(self, context: ModelContext) -> Optional[RoutingRecommendation]:
        """
        Return and validate recommendation, or None when evidence is empty.
        :param context:
        :return:
        """
        if not context.evidence:
            return None

        raw_response = self.generate(context)
        try:
            response = json.loads(raw_response)
        except (json.JSONDecodeError, TypeError) as error:
            raise InvalidModelResponse("Expected a JSON object") from error

        if not isinstance(response, dict):
            raise InvalidModelResponse("Expected a JSON object")

        route = response.get("route")
        reason = response.get("reason")
        source = response.get("source")
        heading = response.get("heading")

        if route != "billing_review" and route != "account_support":
            raise InvalidModelResponse("Unknown review route")

        if not isinstance(reason, str) or not reason.strip():
            raise InvalidModelResponse("Reason is required")

        for passage in context.evidence:
            if passage.source == source and passage.heading == heading:
                return RoutingRecommendation(route=route, reason=reason.strip(), policy_passage=passage)

        raise InvalidModelResponse("The cited policy was not in the model context")
