"""
13_coordinated_agents.py

Demonstrated delegation and parallel checks for a simulated robot trip.

A coordinator gives the same trip request to two specialist agents.

It waits for both reports, then decides whether the robot can depart.

Uses only python standard library. No robot moves in this example.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

@dataclass(frozen=True)
class TripRequest:
    """
    The information the specialist need to assess a trip.
    """
    distance: int
    battery: int
    path_open: bool


@dataclass(frozen=True)
class CheckResult:
    """
    One specialist decision and its reason.
    """
    specialist: str
    passed: bool
    reason: str


@dataclass(frozen=True)
class TripDecision:
    """
    The coordinator's decision and the reports behind it.
    """
    approved: bool
    checks: tuple[CheckResult, ...]


class RouteAgent:
    """
    Check whether the requested route is open.
    """
    def run(self, request: TripRequest) -> CheckResult:
        """
        Return a route report without changing the trip.

        :param request:
        :return:
        """
        if not request.path_open:
            return CheckResult("Route agent", False, "The path is blocked.")

        return CheckResult("Route Agent", True, "The path is open.")


class BatteryAgent:
    """
    Check whether the robot can afford the trip.
    """
    def run(self, request: TripRequest) -> CheckResult:
        """
        Require one battery unit per step
        """
        if request.battery < request.distance:
            return CheckResult("Battery Agent", False, "Recharge before departure.")

        return CheckResult("Battery Agent", True, "Enough battery for the trip.")


class CoordinatorAgent:
    """
    Delegate independent checks and combines their reports.
    """
    def __init__(self) -> None:
        """
        Create the two specialist this coordinator can delegate to
        """
        self.route_agent = RouteAgent()
        self.battery_agent = BatteryAgent()

    def run(self, request: TripRequest) -> TripDecision:
        """
        Approve departure only when both specialist checks pass.

        :param request:
        :return:
        """
        with ThreadPoolExecutor(max_workers=2) as workers:
            # Submit both checks before waiting for either result.
            route_future = workers.submit(self.route_agent.run, request)
            battery_future = workers.submit(self.battery_agent.run, request)

            checks = (route_future.result(), battery_future.result())

        return TripDecision(
            approved=all(check.passed for check in checks),
            checks=checks,
        )

def main():
    """
    Compare an approved trip with one blocked by a specialist.

    :return:
    """
    coordinator = CoordinatorAgent()
    scenarios = [
        (
            "Ready to depart",
            TripRequest(distance = 2, battery = 2, path_open = True)
        ),
        (
            "Blocked path",
            TripRequest(distance=2, battery=2, path_open=False)
        )
    ]

    for name, request in scenarios:
        print(f"\nScenario: {name}")
        decision = coordinator.run(request)

        for check in decision.checks:
            print(f"{check.specialist}: {check.reason}")

        print("Decision:", "Ready to depart" if decision.approved else "Stay put")


if __name__ == "__main__":
    main()
