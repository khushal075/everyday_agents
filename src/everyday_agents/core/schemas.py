"""Shared records for an agent's decision, action outcome, and completed run.

Prediction structures, score meanings, and domain validation belong to each
agent. The core accepts those outputs without requiring a label or score.
"""

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar


PredictionT = TypeVar("PredictionT")


@dataclass(frozen=True)
class Decision:
    """An action selected by a policy, with its reason and tool parameters.

    The tool layer resolves the action name and validates its parameters.
    """

    action: str
    reason: str
    parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.action.strip():
            raise ValueError("Decision action must not be empty")
        if not self.reason.strip():
            raise ValueError("Decision reason must not be empty")


@dataclass(frozen=True)
class ActionResult:
    """A tool's reported outcome, before any runtime verification.

    A failed action may include an error explanation and partial output in
    details. Verification and retry decisions belong to the runtime.
    """

    success: bool
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class AgentRun(Generic[PredictionT]):
    """One completed prediction/decision/action cycle.

    PredictionT is the agent's own output type: a scalar, domain dataclass,
    ranking, or another structure. For example, AgentRun[float] can carry a
    score directly without wrapping it in a universal Prediction class.

    Failures before these stages complete are handled by the runtime.
    """

    prediction: PredictionT
    decision: Decision
    result: ActionResult


# Frozen dataclasses prevent field reassignment, not mutation of nested values.
# Use JSON-compatible payloads or a domain serializer when persisting runs.
