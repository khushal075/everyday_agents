"""
Decide whether a failed job should retry, stop, or escalate.
"""

import math
from dataclasses import dataclass
from typing import Literal

RecoveryAction = Literal[
    "retry",
    "cancel",
    "escalate",
]

@dataclass(frozen=True)
class RecoveryDecision:
    """
    The next action after a failed attempt.
    """
    action: RecoveryAction
    reason: str
    delay_seconds: float = 0.0


class RecoveryPolicy:
    """
    Limit attempts and calculate exponential retry delays.
    """
    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay_seconds: float = 1.0,
        max_delay_seconds: float = 30.0,
    ):
        if max_attempts < 1:
            raise ValueError("Max attempts must be at least 1.")

        if not (math.isfinite(initial_delay_seconds) and math.isfinite(max_delay_seconds)
                and 0 < initial_delay_seconds <= max_delay_seconds):
            raise ValueError("Initial delay seconds must positive and in between 0 and max_delay_seconds.")

        self.max_attempts = max_attempts
        self.initial_delay_seconds = initial_delay_seconds
        self.max_delay_seconds = max_delay_seconds


    def decide(
        self,
        attempt: int,
        *,
        retryable: bool,
        cancelled: bool = False,
    ) -> RecoveryDecision:
        """
        Choose what happens after the numbered attempt failed.
        (attempt=1 means the first attempt has already failed.)
        """

        if attempt < 1 :
            raise ValueError("Attempt must be at least 1.")

        if cancelled:
            return RecoveryDecision("cancel", reason="Cancellation was requested")

        if not retryable:
            return RecoveryDecision("escalate", reason="The failure require review")

        if attempt >= self.max_attempts:
            return RecoveryDecision("escalate", reason="Maximum number of attempts reached")

        delay = self.initial_delay_seconds
        for _ in range(attempt - 1):
            delay = min(delay * 2, self.max_delay_seconds)
            if delay == self.max_delay_seconds:
                break

        return RecoveryDecision(
            action="retry",
            reason="A retryable attempt occurred",
            delay_seconds=delay,
        )
