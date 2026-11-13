"""
11_safe_recovery.py

Demonstrate how an agent recovers when a delivery tool times out.

A timeout can happen before or after the delivery is recorded.
The agent checks the record and retries only within a fixed budget.

Uses only the python standard library.
The delivery service, timeouts, and records are simulated in memory.
"""

from dataclasses import dataclass
from typing import Literal

TimeoutMode = Literal["before_delivery", "after_delivery"]
RunStatus = Literal["delivered", "delivery_unconfirmed"]


@dataclass(frozen=True)
class DeliveryRequest:
    """
    Identify onr delivery and the package it should deliver.
    """
    operation_id: str
    package: str


class DeliveryService:
    """
    Simulate delivery tool and look up tool for its records.
    """
    def __init__(self, timeout_mode: TimeoutMode) -> None:
        """
        Choose when the first new delivery request will time out.

        :param timeout_mode:
        """
        self.timeout_mode = timeout_mode
        self.simulate_timeout = True
        self.records: dict[str, DeliveryRequest] = {}

    def lookup(self, operation_id: str) -> DeliveryRequest | None:
        """
        Return the recorded delivery for this ID, if one exists.

        :param operation_id:
        :return:
        """
        return self.records.get(operation_id)

    def deliver(self, request: DeliveryRequest) ->  None:
        """
        Record a delivery once; recognize repeated requires by their ID

        :param request:
        :return:
        """
        existing = self.lookup(request.operation_id)

        if existing is not None:
            if existing != request:
                raise ValueError("This operation ID belongs to a different delivery.")
            print("Already recorded. No duplicate delivery.")
            return

        should_timeout = self.simulate_timeout
        self.simulate_timeout = False
        if should_timeout and self.timeout_mode == "before_delivery":
            raise TimeoutError("Request timed out before delivery.")

        # In this simulation, writing the record is the delivery itself.
        self.records[request.operation_id] = request
        print(f"Delivered: {request.package}")

        if should_timeout and self.timeout_mode == "after_delivery":
            raise TimeoutError("Confirmed timed out after delivery.")


class Agent:
    """
    Use delivery and lookups tools to recover form uncertain outcome.
    """

    def __init__(self, service: DeliveryService) -> None:
        self.service = service

    def run(
            self,
            request: DeliveryRequest,
            max_attempts: int = 2,
    )-> RunStatus:
        """
        Confirm the delivery or stop when the attempt budget runs out.

        :param request:
        :param max_attempts:
        :return:
        """
        if not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer.")

        for attempt in range(1, max_attempts + 1):
            print(f"Attempt {attempt} - operation ID: {request.operation_id}")

            try:
                self.service.deliver(request)
            except TimeoutError as error:
                # A timeout tells the agent nothing about the delivery's effect
                print("Timed out. Checking the delivery record.")

            recorded = self.service.lookup(request.operation_id)

            if recorded == request:
                return "delivered"

            if recorded is not None:
                raise ValueError("The delivery record does not match the request.")

            if attempt < max_attempts:
                print("No record found. Retrying with the same operation ID.")

        return "delivery_unconfirmed"


def main():
    """
    Show recovery after a lost confirmation and before a delivery.

    :return:
    """
    request = DeliveryRequest(
        operation_id="delivery-001",
        package="Robot battery",
    )

    # For each scenario starts with a separate, empty service.
    for mode in ("after_delivery", "before_delivery"):
        print(f"\nScenario: {mode}")
        service = DeliveryService(timeout_mode=mode)
        agent = Agent(service)

        print("Final status:", agent.run(request))
        print("Delivery records:", len(service.records))


if __name__ == "__main__":
    main()
