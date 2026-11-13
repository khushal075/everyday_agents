"""
04_authorization_and_approval.py


Move a simulated robot to its destination. Moving is allowed for both roles.

Recharging require the operator role and human approval.

Run normally to approve ro reject a recharge at terminal.

Run with --viewer to see authorization block recharging before prompting.

Uses only the Python standard library. Approval applies to the current request only.

it's not saved for later use.
"""

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

Action = Literal["move", "recharge"]
Role = Literal["viewer", "operator"]
RunStatus = Literal["goal_reached", "not_authorized", "approval_denied", "step_limit_reached"]


@dataclass(frozen=True)
class Observation:
    """
    Robot current distance from goal and remaining battery units.
    """
    distance: int
    battery: int


@dataclass(frozen=True)
class ToolCall:
    """
    The next action and amount proposed for execution.
    """
    action: Action
    amount: int


class Environment:
    """
    Simulate the robot and the tools that change its state.
    """
    def __init__(self):
        """
        Start three step away with battery for one move.
        """
        self.distance = 3
        self.battery = 1

    def observe(self) -> Observation:
        return Observation(distance=self.distance, battery=self.battery)

    def move(self, steps: int) -> None:
        """
        Move towards the destination and spent one battery uint per step.

        :param steps:
        :return:
        """

        if not 1 <= steps <= min(self.distance, self.battery):
            raise ValueError("Movement exceeds the remaining distance or battery")

        self.distance -= steps
        self.battery -= steps

    def recharge(self, units: int) -> None:
        """
        Add battery units without exceeding the capacity.

        :param units:
        :return:
        """

        if not 1 <= units <= 2 - self.battery:
            raise ValueError("Recharge amount exceeds the available battery capacity")

        self.battery += units


class DecisionPolicy:
    """
    Proposed the next action based on what a robot observe.

    """
    def decide(self, observation: Observation) -> ToolCall:
        """
        Recharge when battery is empty; Otherwise move one step.

        :param observation:
        :return:
        """
        if observation.battery == 0:
            return ToolCall(action="recharge", amount=2)

        return ToolCall(action="move", amount=1)

class AuthorizationPolicy:
    """
    Check whether the user's role permits the proposed action.
    """
    def allow(self, role: Role, call: ToolCall) -> bool:
        if call.action == "move":
            return role in ("viewer", "operator")

        return call.action == "recharge" and role == "operator"


def ask_for_approval(call: ToolCall) -> bool:
    """
    Show the exact request and approve only an explicit 'yes'.

    :param call:
    :return:
    """
    try:
        answer = input(f"Approve {call.action} by {call.amount} units ? (yes/no) ")
    except EOFError:
        return False

    return answer.strip().lower() == "yes"


class Agent:
    """
    Propose, Authorize, Approve when required, and execute each action.
    """
    def __init__(
            self,
            environment: Environment,
            role: Role,
            approve: Callable[[ToolCall], bool],
    ) -> None:
        """
        Connect the environment, policies, tools, and approval function.

        :param environment:
        :param role:
        :param approve:
        """
        self.environment = environment
        self.role = role
        self.approve = approve
        self.decision_policy = DecisionPolicy()
        self.authorization_policy = AuthorizationPolicy()
        self.tool: dict[Action, Callable[[int], None]] = {
            "move": environment.move,
            "recharge": environment.recharge,
        }

    def run(self, max_steps: int = 10) -> RunStatus:
        """
        Run until reach the goal, a blocked request or a step limit.

        :param max_steps:
        :return:
        """
        if max_steps < 1:
            raise ValueError("max_steps must be a positive integer.")

        for _ in range(max_steps):
            observation = self.environment.observe()
            if observation.distance == 0:
                return "goal_reached"

            call = self.decision_policy.decide(observation)

            # Check permission before asking a human
            if not self.authorization_policy.allow(self.role, call):
                print(f"Blocked: {self.role} cannot {call.action}")
                return "not_authorized"

            # Shows the request before running the recharge tool
            if call.action == "recharge" and not self.approve(call):
                print("Recharge was not approved")
                return "approval_denied"

            self.tool[call.action](call.amount)
            after = self.environment.observe()
            print(f"{call.action}: distance={after.distance}, battery={after.battery}")

            if after.distance == 0:
                return "goal_reached"

        return "step_limit_reached"


def main():
    """
    Run the demo as an operator, or as a viewer with restricted access.

    :return:
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--viewer", action="store_true")
    args = parser.parse_args()
    role: Role = "viewer" if args.viewer else "operator"
    agent = Agent(environment=Environment(), role=role, approve=ask_for_approval)
    print("Final status:", agent.run())

if __name__ == "__main__":
    main()
