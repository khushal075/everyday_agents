"""
05_verified_feedback.py

Demonstrate how agent checks the effect of a tool call.

Goal:
    Reach a destination three steps away.

Flow:
    Observe --> Decide --> execute --> observe again --> verify.

Uses only the python standard library. The robot and its sensors are simulated.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

Action = Literal["move", "recharge"]
RunStatus = Literal["goal_reached", "tool_failed", "verification_failed", "step_limit_reached"]

@dataclass(frozen=True)
class Observation:
    """
    A snapshot of the robot's distance and battery.
    """
    distance: int
    battery: int


@dataclass(frozen=True)
class ToolResult:
    """
    What are the tools report about its execution.
    """
    success: bool
    message: str


class Environment:
    """
    Simulate the robot sensors snd tools.
    """

    def __init__(self, stuck: bool = False) -> None:
        self.distance = 3
        self.battery = 1
        self.stuck = stuck

    def observe(self) -> Observation:
        """
        Read the current state into new Observation.

        :return:
        """
        return Observation(distance=self.distance, battery=self.battery)

    def move(self) -> ToolResult:
        """
        Attempt one move, with an option simulated fault.

        :return:
        """
        if self.distance <= 0 or self.battery <= 0:
            return ToolResult(success=False, message="Cannot move from the current state.")

        if not self.stuck:
            self.distance -= 1
            self.battery -= 1

        # Simulate the tool that report success even when the robot is stuck.
        return ToolResult(success=True, message="Moved reported successfully.")


    def recharge(self) -> ToolResult:
        """
        Restore the battery to 2 units (Max capacity).

        :return:
        """
        self.battery = 2
        return ToolResult(success=True, message="Recharged reported successfully.")


class OutcomeVerifier:
    """
    Compare the observed state change with the expected effect.
    """

    def verify(
            self,
            action: Action,
            before: Observation,
            after: Observation,
    ) -> bool:
        """
        Return whether the new state matches the action's expected effect.
        :return:
        """
        if action == 'move':
            expected = Observation(before.distance - 1, before.battery - 1)
        else:
            expected = Observation(before.distance, 2)

        return expected == after

class Agent:
    """
    Choose actions and continue only after their effects are verified.
    """
    def __init__(self, environment: Environment) -> None:
        """
        Connects the robot tools to the outcome verifier.

        :param environment:
        """

        self.environment = environment
        self.verifier = OutcomeVerifier()
        self.tools: dict[Action, Callable[[], ToolResult]] = {
            "move": environment.move,
            "recharge": environment.recharge,
        }

    def choose_action(self, observation: Observation) -> Action:
        """
        Recharge an empty battery; Otherwise move 1 step.

        :param observation:
        :return:
        """
        return "recharge" if observation.battery == 0 else "move"

    def run(self, max_steps: int = 10) -> RunStatus:
        """
        Run until completion, failure or step limit.
        :param max_steps:
        :return:
        """
        if not isinstance(max_steps, int) or max_steps < 1:
            raise ValueError("max_steps must be a positive integer.")

        for step in range(1, max_steps + 1):
            before = self.environment.observe()
            if before.distance == 0:
                return "goal_reached"

            action = self.choose_action(before)
            result = self.tools[action]()
            print(f"Step {step}: {result.message}")

            if not result.success:
                return "tool_failed"

            # Read the state again before trusting the tool's success report.
            after = self.environment.observe()
            if not self.verifier.verify(action, before, after):
                print(f"Verification failed: {before} → {after}")
                return "verification_failed"

            print(f"Verified: {after}")
            if after.distance == 0:
                return "goal_reached"

        return "step_limit_reached"

def main():
    """
    Compare a normal run with a misleading tool success report.

    :return:
    """
    print("Normal robot")
    print("Final status: ", Agent(Environment()).run())

    print("\nStuck robot:")
    print("Final Status: ", Agent(Environment(stuck=True)).run())


if __name__ == "__main__":
    main()
