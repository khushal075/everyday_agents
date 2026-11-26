"""
28_execution_wide_budgets.py

Give a whole task one shared budget for time, tool calls and cost,
and stop cleanly when any of them runs out.

Scenario:
    The same robot as examples 01-27, with three deliveries in one task:
    the lab, the mailroom and the workshop. The battery holds two units.
    Every decision is a model call, and every move or recharge is a tool call.

Goal:
    Do as much of the task as the budget allows, never go over it,
    and always have enough left to report what was done.

Difference from examples 16, 19 and 22:
    Those limited one thing at a time: steps, context size, or cost per call.
    Here one budget covers the entire task, across every delivery, and every
    model call and tool call is charged to it.

Flow:
    1. Create one Budget for the task: a deadline, a tool-call limit, a cost limit.
    2. Set aside a reserve for the final report.
    3. Before each step (a model call plus a tool call), ask the budget whether
       the whole step can be afforded.
    4. If not, stop at that point, between actions, and record why.
    5. Use the reserve to write the final report, including unfinished work.

New concepts:
    1. One budget is shared by everything in the task, not set per step.
    2. Check before spending, so the simulated budget is never exceeded.
    3. Keep a reserve, so there is always enough left to finish properly.
    4. Stopping early is a normal outcome with a reason, not a crash.
    5. Report partial results: what finished, and what did not.

Modes:
    1. --limits enough      Everything fits.
    2. --limits tools       Runs out of tool calls.
    3. --limits cost        Runs out of money.
    4. --limits deadline    Runs out of time.

No model is needed: the budget is plain code. Times and costs are assumed
numbers on a simulated clock, so every run gives the same result.
This demonstrates accounting and admission checks, not live enforcement:
there are no actual model requests, token usage, timers, or preempted tools.
A live adapter must account for actual usage, set request timeouts from
the remaining deadline, and reconcile costs and effects after uncertain outcomes.

Requirements:
    Python's standard library only.
"""

import argparse
from dataclasses import dataclass

BATTERY_CAPACITY = 2

# Assumed prices and durations, for illustration.
MODEL_CALL_COST = 1.0
MODEL_CALL_SECONDS = 1.0
TOOL_CALL_SECONDS = 0.2

DELIVERIES = [("lab", 3, 1), ("mailroom", 2, 2), ("workshop", 4, 1)]  # name, distance, battery

LIMITS = {
    "enough": {"seconds": 20.0, "tool_calls": 20, "cost": 15.0},
    "tools": {"seconds": 20.0, "tool_calls": 6, "cost": 15.0},
    "cost": {"seconds": 20.0, "tool_calls": 20, "cost": 6.0},
    "deadline": {"seconds": 6.0, "tool_calls": 20, "cost": 15.0},
}


@dataclass(frozen=True)
class Charge:
    """
    The price of one operation.
    """
    seconds: float
    tool_calls: int = 0
    cost: float = 0.0


MODEL_CALL = Charge(seconds=MODEL_CALL_SECONDS, cost=MODEL_CALL_COST)
TOOL_CALL = Charge(seconds=TOOL_CALL_SECONDS, tool_calls=1)
# One step is a decision and an action. Check both before starting, so the task
# never pays for a decision it cannot act on.
STEP = Charge(seconds=MODEL_CALL_SECONDS + TOOL_CALL_SECONDS, tool_calls=1, cost=MODEL_CALL_COST)
REPORT = MODEL_CALL  # The final report is one more model call.


class Budget:
    """
    Track what the whole task has spent, and refuse anything it cannot afford.
    """

    def __init__(self, seconds: float, tool_calls: int, cost: float, reserve: Charge) -> None:
        """
        :param seconds:    The deadline for the whole task, on the simulated clock.
        :param tool_calls: The most tool calls the whole task may make.
        :param cost:       The most money the whole task may spend.
        :param reserve:    Kept back for the final report.
        """
        self.limits = Charge(seconds=seconds, tool_calls=tool_calls, cost=cost)
        self.reserve = reserve
        self.spent = Charge(seconds=0.0)

    def shortfall(self, charge: Charge, use_reserve: bool = False) -> str | None:
        """
        Check whether a charge fits, without spending anything.

        :param charge:      The operation about to happen.
        :param use_reserve: True only for the final report.
        :return: Which limit it would break, or None if it fits.
        """
        keep = Charge(seconds=0.0) if use_reserve else self.reserve
        if self.spent.seconds + charge.seconds + keep.seconds > self.limits.seconds:
            return "deadline"
        if self.spent.tool_calls + charge.tool_calls + keep.tool_calls > self.limits.tool_calls:
            return "tool-call limit"
        if self.spent.cost + charge.cost + keep.cost > self.limits.cost:
            return "cost limit"
        return None

    def spend(self, charge: Charge) -> None:
        """
        Record a charge that was checked first.

        :param charge: The operation that happened.
        :return: None.
        """
        self.spent = Charge(
            seconds=self.spent.seconds + charge.seconds,
            tool_calls=self.spent.tool_calls + charge.tool_calls,
            cost=self.spent.cost + charge.cost,
        )

    def __str__(self) -> str:
        return (
            f"{self.spent.seconds:.1f}/{self.limits.seconds:g}s, "
            f"{self.spent.tool_calls}/{self.limits.tool_calls} tool calls, "
            f"{self.spent.cost:g}/{self.limits.cost:g} cost"
        )


class BudgetExhausted(Exception):
    """
    Raised when the next operation does not fit in the budget.
    """


class Delivery:
    """
    One trip, run one decision and one action at a time, charging the shared budget.
    """

    def __init__(self, name: str, distance: int, battery: int, budget: Budget) -> None:
        """
        :param name:     Where the package goes.
        :param distance: Steps to get there.
        :param battery:  Starting battery units.
        :param budget:   The task's shared budget.
        """
        self.name = name
        self.distance = distance
        self.battery = battery
        self.budget = budget

    def run(self) -> None:
        """
        Decide (a model call) and act (a tool call) until the robot arrives.

        :return: None.
        """
        while self.distance > 0:
            problem = self.budget.shortfall(STEP)
            if problem is not None:
                raise BudgetExhausted(problem)

            self.budget.spend(MODEL_CALL)
            action = "recharge" if self.battery == 0 else "move"

            self.budget.spend(TOOL_CALL)
            if action == "recharge":
                self.battery = BATTERY_CAPACITY
            else:
                steps = min(self.battery, self.distance)
                self.distance -= steps
                self.battery -= steps
            print(f"  {self.name}: {action} -> distance {self.distance}, battery {self.battery}  [{self.budget}]")


class Task:
    """
    Run every delivery against one budget, then report.
    """

    def __init__(self, budget: Budget) -> None:
        """
        :param budget: Shared by every delivery and the report.
        """
        self.budget = budget

    def run(self) -> None:
        """
        Deliver until done or out of budget, then write the report from the reserve.

        :return: None.
        """
        if self.budget.shortfall(REPORT, use_reserve=True) is not None:
            raise ValueError("The budget is too small even for the final report.")

        done: list[str] = []
        unfinished: list[str] = []
        reason = ""

        for name, distance, battery in DELIVERIES:
            if reason:
                unfinished.append(f"{name} (not started)")
                continue
            delivery = Delivery(name, distance, battery, self.budget)
            try:
                delivery.run()
                done.append(name)
            except BudgetExhausted as error:
                reason = str(error)
                print(f"  Stopped before the next step: the {reason} would be exceeded.")
                started = delivery.distance < distance or delivery.battery != battery
                unfinished.append(f"{name} ({delivery.distance} step(s) left)" if started else f"{name} (not started)")

        # The reserve guarantees this fits.
        self.budget.spend(REPORT)

        print("\nReport:")
        print(f"  Delivered: {', '.join(done) or 'nothing'}")
        if unfinished:
            print(f"  Unfinished: {', '.join(unfinished)}; stopped by the {reason}")
        print(f"  Spent: {self.budget}")


def main() -> None:
    """
    Run the three deliveries under one of the preset budgets.

    :return: None.
    """
    parser = argparse.ArgumentParser(description="Share one budget across a whole task.")
    parser.add_argument("--limits", choices=sorted(LIMITS), default="enough")
    args = parser.parse_args()

    limits = LIMITS[args.limits]
    budget = Budget(limits["seconds"], limits["tool_calls"], limits["cost"], reserve=REPORT)
    print(f"Budget ({args.limits}): {limits['seconds']:g}s, {limits['tool_calls']} tool calls, "
          f"{limits['cost']:g} cost; reserve kept for the report: one model call\n")
    try:
        Task(budget).run()
    except ValueError as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    # Example commands:
    #   uv run python 28_execution_wide_budgets.py --limits enough
    #   uv run python 28_execution_wide_budgets.py --limits tools
    #   uv run python 28_execution_wide_budgets.py --limits cost
    #   uv run python 28_execution_wide_budgets.py --limits deadline
    main()
