"""
31_retry_with_backoff.py

Retry a model call that fails for temporary reasons, waiting longer each time.

Scenario:
    The same robot as examples 01-30. Before each move it asks a hosted
    model for the next action. The model service is busy: sometimes it
    answers "429 Too Many Requests" or "503 Service Unavailable".

Goal:
    Get an answer when the failure is temporary, give up quickly when it
    is not, and never hammer a service that is already overloaded.

Difference from example 11:
    Example 11 retried a delivery after a timeout and used an operation ID
    so the delivery was never done twice. Here the failures come from the
    model service, and the question is how long to wait between attempts.

Flow:
    For each attempt:
        1. Call the service.
        2. Success: return the answer.
        3. A permanent error (400 Bad Request): stop at once; retrying
           would only fail again.
        4. A temporary error (429, 503): wait, then try again.
           - If the service says how long to wait (Retry-After), wait that long.
           - Otherwise wait 1s, 2s, 4s, ... (exponential backoff), plus a
             small random amount (jitter).
        5. Stop after the attempt limit.

New concepts:
    1. Only temporary errors are worth retrying.
    2. Exponential backoff gives an overloaded service time to recover.
    3. Jitter spreads retries out, so many clients do not retry at the same moment.
    4. Retry-After from the service takes priority over your own schedule.
    5. A retry limit bounds the total wait.

Modes:
    --scenario busy         Two 429s, then success.
    --scenario retry_after  One 429 that says "wait 5 seconds", then success.
    --scenario bad_request  A 400: no retry.
    --scenario outage       503 every time: give up after the limit.

No real waiting happens: a simulated clock records the delays, so the
example runs instantly and gives the same result every time.

Requirements:
    Python's standard library only.
"""

import argparse
import random
from dataclasses import dataclass

MAX_ATTEMPTS = 5
BASE_DELAY = 1.0
MAX_DELAY = 30.0
RETRYABLE = {429, 503}


@dataclass(frozen=True)
class Response:
    """
    What the simulated service returned for one call.
    """
    status: int
    body: str = ""
    retry_after: float | None = None


SCENARIOS = {
    "busy": [Response(429), Response(429), Response(200, "move 1")],
    "retry_after": [Response(429, retry_after=5.0), Response(200, "move 1")],
    "bad_request": [Response(400, "unknown field 'speed'")],
    "outage": [Response(503)] * 10,
}


class GiveUp(Exception):
    """
    Raised when the call cannot succeed, or the retry limit is reached.
    """


class SimulatedClock:
    """
    Record waits instead of sleeping, so the example runs instantly.
    """

    def __init__(self) -> None:
        self.now = 0.0

    def sleep(self, seconds: float) -> None:
        """
        :param seconds: How long a real client would wait.
        :return: None.
        """
        self.now += seconds


class ModelService:
    """
    A simulated model service that returns a fixed sequence of responses.
    """

    def __init__(self, responses: list[Response]) -> None:
        """
        :param responses: Returned in order, one per call.
        """
        self.responses = list(responses)

    def call(self, prompt: str) -> Response:
        """
        :param prompt: Ignored by the simulation.
        :return: The next response.
        """
        return self.responses.pop(0)


class RetryingClient:
    """
    Call the service, retrying temporary failures with exponential backoff and jitter.
    """

    def __init__(self, service: ModelService, clock: SimulatedClock, rng: random.Random) -> None:
        """
        :param service: The model service.
        :param clock:   Used for waiting.
        :param rng:     Source of jitter; seeded so runs repeat exactly.
        """
        self.service = service
        self.clock = clock
        self.rng = rng

    def delay(self, attempt: int, response: Response) -> float:
        """
        Choose how long to wait before the next attempt.

        :param attempt:  The attempt that just failed, starting at 1.
        :param response: The failed response.
        :return: Seconds to wait.
        """
        if response.retry_after is not None:
            return response.retry_after
        backoff = min(MAX_DELAY, BASE_DELAY * 2 ** (attempt - 1))
        jitter = self.rng.uniform(0, backoff * 0.25)
        return backoff + jitter

    def call(self, prompt: str) -> str:
        """
        :param prompt: What to ask the model.
        :return: The model's answer.
        """
        for attempt in range(1, MAX_ATTEMPTS + 1):
            response = self.service.call(prompt)
            print(f"  [{self.clock.now:5.1f}s] attempt {attempt}: HTTP {response.status} {response.body}".rstrip())

            if response.status == 200:
                return response.body
            if response.status not in RETRYABLE:
                raise GiveUp(f"HTTP {response.status} is permanent; retrying would not help.")
            if attempt == MAX_ATTEMPTS:
                break

            wait = self.delay(attempt, response)
            source = "service asked for" if response.retry_after is not None else "backoff"
            print(f"           waiting {wait:.1f}s ({source})")
            self.clock.sleep(wait)

        raise GiveUp(f"Still failing after {MAX_ATTEMPTS} attempts.")


def main() -> None:
    """
    Ask for the robot's next action under one failure scenario.

    :return: None.
    """
    parser = argparse.ArgumentParser(description="Retry temporary failures with backoff.")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="busy")
    args = parser.parse_args()

    clock = SimulatedClock()
    client = RetryingClient(ModelService(SCENARIOS[args.scenario]), clock, random.Random(7))
    print("Robot: distance 3, battery 1 of 2. Asking the model for the next action.")
    try:
        answer = client.call("Distance 3, battery 1. Next action?")
        print(f"Answer: {answer} (total waiting: {clock.now:.1f}s)")
    except GiveUp as error:
        print(f"Gave up: {error} (total waiting: {clock.now:.1f}s)")
        print("The robot stays where it is; no action without an answer.")


if __name__ == "__main__":
    # Example commands:
    #   uv run python 31_retry_with_backoff.py --scenario busy
    #   uv run python 31_retry_with_backoff.py --scenario retry_after
    #   uv run python 31_retry_with_backoff.py --scenario bad_request
    #   uv run python 31_retry_with_backoff.py --scenario outage
    main()
