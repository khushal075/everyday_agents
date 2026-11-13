"""
15_evaluation_and_observability.py

Record a structured trace for each agent run and evaluate its decision against fixed expectations.

Run with --threshold 10 to introduce a regression and watch the evaluation catch it.
Uses only python standard library.
"""

import argparse
import json
from dataclasses import dataclass, asdict
from time import perf_counter
from typing import Literal, List

Decision = Literal["recharge", "ready_to_move", "cannot_decide"]

@dataclass(frozen=True)
class RunTrace:
    """
    Record what the agent observed, decided and spent on one run.
    """
    robot_id: str
    battery: int | None
    decision: Decision
    tool_calls: int
    elapsed_ms: float

@dataclass(frozen=True)
class TestCase:
    """
    Describe one input and its independently specified expectations.
    """
    name: str
    robot_id: str
    expected: Decision


def check_battery(robot_id: str) -> int | None:
    readings = {
        "robot-1": 15,
        "robot-2": 80,
        "robot-3": 20,
    }
    return readings.get(robot_id)

class Agent:
    """
    Use the battery reading to recommend what a robot should do.
    """
    def __init__(self, threshold: int = 20) -> None:
        """
        Set the battery level below which the robot should recharge.

        :param threshold:
        """
        self.threshold = threshold

    def run(self, robot_id: str) -> RunTrace:
        """
        Call the tool once, make a decision and record the run.
        :param robot_id:
        :return:
        """
        started = perf_counter()
        battery = check_battery(robot_id)
        decision = Decision
        if battery is None:
            decision = "cannot_decide"
        elif battery < self.threshold:
            decision = "recharge"
        else:
            decision = "ready_to_move"

        return RunTrace(
            robot_id=robot_id,
            battery=battery,
            decision=decision,
            tool_calls=1,
            elapsed_ms=round((perf_counter() - started) * 1_000, 3),
        )

class Evaluator:
    """
    Compare Agent decision against a fixed set of test cases.
    :return:
    """
    def __init__(self, cases: List[TestCase]) -> None:
        self.cases = tuple(cases)

    def evaluate(self, agent: Agent) -> int:
        """
        Print each run's trace and return the number of failed cases.

        :param agent:
        :return:
        """
        failure = 0
        for case in self.cases:
            trace = agent.run(case.robot_id)
            print(f"Trace:", json.dumps(asdict(trace)))

            if trace.decision == case.expected:
                print(f"PASS: {case.name}")

            else:
                failure += 1
                print(f"FAIL: {case.name} -- expected: {case.expected}, got: {trace.decision}")

        total = len(self.cases)
        print(f"\nSummary: {total - failure} / {total} passed")
        return failure

def main():
    """
    Run the evaluation and return a nonzero exit code on failure.

    :return:
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=int, default=20)
    args = parser.parse_args()

    if not 0 <= args.threshold <= 100:
        parser.error("--threshold must be between 0 and 100")

    # Keep expectations fixed when changing the agent's threshold.

    cases = [
        TestCase(name="Low battery", robot_id="robot-1", expected="recharge"),
        TestCase(name="Enough battery", robot_id="robot-2", expected="ready_to_move"),
        TestCase(name="Exactly at 20% boundary", robot_id="robot-3", expected="ready_to_move"),
        TestCase(name="Unknown robot", robot_id="robot-4", expected="cannot_decide"),
    ]
    evaluator = Evaluator(cases)
    failures = evaluator.evaluate(Agent(args.threshold))
    return 1 if failures else 0

if __name__ == "__main__":
    raise SystemExit(main())
