"""Interfaces and orchestration for one bounded agent cycle.

Predictors produce domain-specific outputs. Policies choose actions. Tools
execute and verify those actions. Exceptions propagate to the caller; this
runtime does not retry actions, suppress errors, or enforce approval policies.
"""

from dataclasses import replace
from typing import Protocol

from .schemas import ActionResult, AgentRun, Decision


class Predictor[InputT, PredictionT](Protocol):
    """Transform an input into a prediction without choosing an action."""

    def predict(self, input_data: InputT) -> PredictionT: ...


class Policy[PredictionT](Protocol):
    """Choose an action using the predictor's output."""

    def decide(self, prediction: PredictionT) -> Decision: ...


class Tool[InputT](Protocol):
    """Execute an allowed decision and check its reported outcome.

    Implementations validate action names and parameters and enforce any
    approval requirements before performing side effects. Result details
    should contain the identifiers needed to verify the action.
    """

    def execute(self, input_data: InputT, decision: Decision) -> ActionResult: ...

    def verify(self, result: ActionResult) -> bool: ...


class Agent[InputT, PredictionT]:
    """Coordinate predict → decide → execute → verify exactly once per run.

    Explicit execution failures are returned without verification. Failed
    verification produces an unsuccessful result while retaining tool details.
    Exceptions from any stage propagate unchanged and stop later stages.
    A caller should inspect side effects before retrying after an exception.
    """

    def __init__(
        self,
        predictor: Predictor[InputT, PredictionT],
        policy: Policy[PredictionT],
        tool: Tool[InputT],
    ) -> None:
        self.predictor = predictor
        self.policy = policy
        self.tool = tool

    def run(self, input_data: InputT) -> AgentRun[PredictionT]:
        """Run one cycle; input and prediction validation belong to components."""
        prediction = self.predictor.predict(input_data)
        decision = self.policy.decide(prediction)
        result = self.tool.execute(input_data, decision)

        if result.success and not self.tool.verify(result):
            result = replace(
                result,
                success=False,
                error=result.error or "Action verification failed",
            )

        return AgentRun(prediction=prediction, decision=decision, result=result)
