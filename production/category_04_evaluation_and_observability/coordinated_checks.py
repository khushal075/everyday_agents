"""
- Run sentiment prediction and policy retrieval independently.
- Combine both results into one feedback routing decision.
- Emit timings for each check and the combined operation.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from everyday_agents.agents.sentiment.baseline import SentimentBaseline
from production.category_02_models_retrieval_and_tools.retrieval import (
    PolicyRetriever,
)
from production.category_04_evaluation_and_observability.telemetry import Telemetry

POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "category_02_models_retrieval_and_tools/fixtures/support_policy.md"
)


@dataclass(frozen=True)
class CheckResult:
    """
    - Hold one independent check's finding.
    - Preserve its name and elapsed time for tracing.
    """

    name: str
    finding: str
    duration_ms: float


@dataclass(frozen=True)
class CoordinatedDecision:
    """
    - Hold the proposed feedback action.
    - Explain how the independent findings contributed to it.
    """

    action: str
    reason: str


class FeedbackCoordinator:
    """
    - Run sentiment and policy checks concurrently.
    - Wait for both findings before proposing an action.
    - Report check durations through the shared telemetry emitter.
    """

    def __init__(self, telemetry: Telemetry) -> None:
        """
        - Prepare the sentiment predictor and policy retriever.
        - Store the event emitter used for observed timings.
        """
        self.predictor = SentimentBaseline()
        self.retriever = PolicyRetriever(POLICY_PATH)
        self.telemetry = telemetry

    def check_sentiment(self, feedback: str) -> CheckResult:
        """
        - Predict the feedback's sentiment using the baseline.
        - Return the label and elapsed inference time.
        """
        started = perf_counter()
        prediction = self.predictor.predict(feedback)
        return CheckResult(
            name="sentiment",
            finding=prediction.sentiment,
            duration_ms=(perf_counter() - started) * 1_000,
        )

    def check_policy(self, feedback: str) -> CheckResult:
        """
        - Search for the strongest policy match.
        - Return its heading or an empty finding when no passage matches.
        """
        started = perf_counter()
        matches = self.retriever.search(feedback, limit=1)
        return CheckResult(
            name="policy",
            finding=matches[0].passage.heading if matches else "",
            duration_ms=(perf_counter() - started) * 1_000,
        )

    def run(self, feedback: str) -> CoordinatedDecision:
        """
        - Run both checks and collect their findings.
        - Propose review for negative, uncertain, or policy-matching feedback.
        - Emit component and overall timings after the checks finish.
        """
        run_id = uuid4().hex
        started = perf_counter()

        with ThreadPoolExecutor(max_workers=2) as executor:
            sentiment_future = executor.submit(self.check_sentiment, feedback)
            policy_future = executor.submit(self.check_policy, feedback)
            sentiment = sentiment_future.result()
            policy = policy_future.result()

        for check in (sentiment, policy):
            self.telemetry.emit(
                run_id=run_id,
                stage=f"check.{check.name}",
                outcome="passed",
                duration_ms=check.duration_ms,
            )

        needs_review = (
            sentiment.finding in {"negative", "uncertain"}
            or bool(policy.finding)
        )
        decision = CoordinatedDecision(
            action="prepare_review" if needs_review else "record",
            reason=(
                f"Sentiment={sentiment.finding}; "
                f"policy={policy.finding or 'no match'}"
            ),
        )

        self.telemetry.emit(
            run_id=run_id,
            stage="coordination.completed",
            outcome="passed",
            duration_ms=(perf_counter() - started) * 1_000,
        )
        return decision


def main() -> None:
    """
    - Demonstrate feedback with and without a policy match.
    - Print the combined decision for each input.
    """
    coordinator = FeedbackCoordinator(Telemetry())

    for feedback in (
        "I was charged twice for my subscription.",
        "This is excellent",
    ):
        decision = coordinator.run(feedback)
        print(f"Feedback: {feedback}")
        print(f"Decision: {decision.action}")
        print(f"Reason: {decision.reason}\n")


if __name__ == "__main__":
    main()
