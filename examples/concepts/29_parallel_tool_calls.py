"""
29_parallel_tool_calls.py

Run independent checks at the same time, and decide what to do when one fails.

Scenario:
    The same robot as examples 01-28: three moves from the lab, one battery
    unit, a battery that holds two. Before starting, the agent checks three
    things that do not depend on each other: the battery, the route, and
    whether the lab door is open. Each check takes a moment.

Goal:
    Finish the checks quickly, and still make a safe decision when a check
    fails or takes too long.

Flow:
    1. Start all three checks at once instead of one after another.
    2. Give each check its own time limit.
    3. Collect every result, including failures, without letting one
       failure cancel the others.
    4. Decide: required checks (battery, route) must succeed; an optional
       check (door) may fail, and the agent continues with a warning.

New concepts:
    1. Independent tool calls can run in parallel; total time is close to
       the slowest call, not the sum of all calls.
    2. Each call needs its own timeout.
    3. Partial failure: some calls succeed and some fail; the agent must
       handle both in the same decision.
    4. Required and optional calls are treated differently.
    5. Only calls that do not depend on each other can run in parallel.

Modes:
    --scenario all_ok        Every check succeeds.
    --scenario door_timeout  The optional door check is too slow.
    --scenario route_fails   A required check fails.
    Add --sequential to run the same checks one after another and compare the time.

Requirements:
    Python's standard library only. The checks are simulated with short waits.
"""

import argparse
import asyncio
import time
from dataclasses import dataclass

TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True)
class Check:
    """
    One tool call to make before the trip.
    """
    name: str
    seconds: float
    required: bool
    fails: bool = False


@dataclass(frozen=True)
class Result:
    """
    What one check returned, or why it failed.
    """
    check: Check
    ok: bool
    detail: str


SCENARIOS = {
    "all_ok": [
        Check("battery", 0.6, required=True),
        Check("route", 0.8, required=True),
        Check("door", 0.5, required=False),
    ],
    "door_timeout": [
        Check("battery", 0.6, required=True),
        Check("route", 0.8, required=True),
        Check("door", 3.0, required=False),
    ],
    "route_fails": [
        Check("battery", 0.6, required=True),
        Check("route", 0.8, required=True, fails=True),
        Check("door", 0.5, required=False),
    ],
}

ANSWERS = {"battery": "1 of 2 units", "route": "path A clear, 3 steps", "door": "lab door open"}


class RobotTools:
    """
    Simulated tools. Each one waits, as a real network call would.
    """

    async def call(self, check: Check) -> str:
        """
        :param check: Which tool to call.
        :return: The tool's answer.
        """
        await asyncio.sleep(check.seconds)
        if check.fails:
            raise RuntimeError("route service returned an error")
        return ANSWERS[check.name]


class CheckRunner:
    """
    Run checks with a timeout each, in parallel or one at a time.
    """

    def __init__(self, tools: RobotTools) -> None:
        """
        :param tools: The tools to call.
        """
        self.tools = tools

    async def run_one(self, check: Check) -> Result:
        """
        Call one tool, turning a timeout or error into a failed Result.

        :param check: Which tool to call.
        :return: The outcome. This never raises, so one failure cannot stop the others.
        """
        started = time.perf_counter()
        try:
            answer = await asyncio.wait_for(self.tools.call(check), timeout=TIMEOUT_SECONDS)
            result = Result(check, True, answer)
        except asyncio.TimeoutError:
            result = Result(check, False, f"no answer within {TIMEOUT_SECONDS:g}s")
        except RuntimeError as error:
            result = Result(check, False, str(error))
        print(f"  {check.name:<8} finished after {time.perf_counter() - started:.1f}s: "
              f"{'ok' if result.ok else 'FAILED'}, {result.detail}")
        return result

    async def run_all(self, checks: list[Check], parallel: bool) -> list[Result]:
        """
        :param checks:   The checks to make.
        :param parallel: Start them all at once, or one after another.
        :return: One Result per check, in the same order.
        """
        if parallel:
            return list(await asyncio.gather(*(self.run_one(check) for check in checks)))
        return [await self.run_one(check) for check in checks]


class Agent:
    """
    Run the pre-trip checks and decide whether the robot may start.
    """

    def __init__(self, runner: CheckRunner) -> None:
        """
        :param runner: Runs the checks.
        """
        self.runner = runner

    def decide(self, results: list[Result]) -> str:
        """
        Required checks must pass; optional failures become warnings.

        :param results: Every check's outcome.
        :return: The decision.
        """
        failed_required = [r.check.name for r in results if r.check.required and not r.ok]
        failed_optional = [r.check.name for r in results if not r.check.required and not r.ok]

        if failed_required:
            return f"Do not start: required check(s) failed: {', '.join(failed_required)}."
        if failed_optional:
            return f"Start, with a warning: optional check(s) failed: {', '.join(failed_optional)}."
        return "Start: every check passed."

    def run(self, checks: list[Check], parallel: bool) -> None:
        """
        :param checks:   The checks to make.
        :param parallel: Run them at the same time.
        :return: None.
        """
        print(f"Running {len(checks)} checks {'in parallel' if parallel else 'one after another'}:")
        started = time.perf_counter()
        results = asyncio.run(self.runner.run_all(checks, parallel))
        print(f"All checks done in {time.perf_counter() - started:.1f}s")
        print(f"Decision: {self.decide(results)}")


def main() -> None:
    """
    Run the pre-trip checks for one scenario.

    :return: None.
    """
    parser = argparse.ArgumentParser(description="Run independent tool calls in parallel.")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="all_ok")
    parser.add_argument("--sequential", action="store_true", help="Run the checks one after another.")
    args = parser.parse_args()

    Agent(CheckRunner(RobotTools())).run(SCENARIOS[args.scenario], parallel=not args.sequential)


if __name__ == "__main__":
    # Example commands:
    #   uv run python 29_parallel_tool_calls.py
    #   uv run python 29_parallel_tool_calls.py --sequential
    #   uv run python 29_parallel_tool_calls.py --scenario door_timeout
    #   uv run python 29_parallel_tool_calls.py --scenario route_fails
    main()
