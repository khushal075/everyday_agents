"""Assemble the sentiment workflow from independently testable components."""

from everyday_agents.core.agent import Agent, Predictor

from .baseline import SentimentBaseline
from .policy import SentimentPolicy
from .schemas import SentimentOutput
from .tools import FeedbackTool


def create_agent(
    *,
    predictor: Predictor[str, SentimentOutput] | None = None,
    tool: FeedbackTool | None = None,
) -> Agent[str, SentimentOutput]:
    """Create a sentiment agent, using the rules baseline by default.

    Each call creates an independent feedback store unless a tool is provided.
    An alternative predictor can be injected without changing policy or tools.
    Records remain in memory; this factory does not load or train models.
    """
    return Agent(
        predictor=predictor if predictor is not None else SentimentBaseline(),
        policy=SentimentPolicy(),
        tool=tool if tool is not None else FeedbackTool(),
    )
