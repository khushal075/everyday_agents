"""
03_tools_and_decision_policy.py

Demonstrates structured tool calls and tool registry.

Goal:
    Move a simulated robot to its destination.

New concepts:
    - A decision policy returns a ToolCall with named arguments.
    - A Registry describe the available tools.
    - An executor validates and dispatches the tool calls.
    - Each tool return a ToolResult.

Everything runs locally in a simulated environment.
"""

from collections.abc import Callable
from dataclasses import dataclass

@dataclass(frozen=True)
class Observation:
    """
    The environment state visible to Agent.
    """
    distance: int
    battery: int


@dataclass(frozen=True)
class ToolCall:
    """
    A proposed tool invocation, include it's named arguments.
    """
    name: str
    arguments: dict[str, int]


@dataclass(frozen=True)
class ToolResult:
    """
    Result reported by a tool.
    """
    success: bool
    message: str

@dataclass(frozen=True)
class Tool:
    """
    Describe a tool's expected argument and expected function.
    """
    argument_name: str
    handler: Callable[[int], ToolResult]


class Environment:
    def __init__(self):
        self.distance = 3
        self.battery = 1

    def observe(self) -> Observation:
        """
        Return the current state as an Observation object.

        :return:
        """
        return Observation(distance=self.distance, battery=self.battery)

    def move(self, steps: int) -> ToolResult:
        """
        Move the requested steps if distance and battery permit.

        :param steps:
        :return:
        """
        if steps > self.distance:
            return ToolResult(success=False, message="Cannot move beyond destination.")

        if steps > self.battery:
            return ToolResult(success=False, message="Not enough battery.")

        self.distance -= steps
        self.battery -= steps
        return ToolResult(success=True, message=f"Moved {steps} step(s)")

    def recharge(self, units: int) -> ToolResult:
        """
        Add battery units without exceeding the capacity

        :param units:
        :return:
        """
        if self.battery + units > 2:
            return ToolResult(success=False, message="Battery Max capacity (2) will be exceeded.")

        self.battery += units
        return ToolResult(success=True, message=f"Added {units} battery unit(s)")



class DecisionPolicy:
    """
    Choose a tool and its arguments from the current observations.
    """
    def decide(self, observation: Observation) -> ToolCall:
        """
        Recharge an empty battery; Otherwise move to next step.
        :param observation:
        :return:
        """
        if observation.battery == 0:
            return ToolCall(
                name="recharge",
                arguments={"units": 2},
            )
        return ToolCall(
            name="move",
            arguments={"steps": 1},
        )

class ToolExecutor:
    """
    Validate structured requests and invoke registered tools.
    """
    def __init__(self, environment: Environment) -> None:
        self.registry: dict[str, Tool] = {
            "move": Tool(argument_name="steps", handler=environment.move),
            "recharge": Tool(argument_name="units", handler=environment.recharge),
        }

    def execute(self, call: ToolCall) -> ToolResult:
        """
        Reject invalid requests before calling the tool.

        Validation checks:
            - The tool exists.
            - Exactly the expected argument is supplied.
            - Its value is positive integer.
        :param call:
        :return:
        """
        tool = self.registry.get(call.name)
        if tool is None:
            return ToolResult(success=False, message=f"Unknown tool: {call.name}")

        if set(call.arguments) != {tool.argument_name}:
            return ToolResult(
                success=False,
                message=f"Expected exactly one argument: {tool.argument_name}",
            )

        value = call.arguments[tool.argument_name]

        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value <= 0
        ):
            return ToolResult(
                success=False,
                message="Argument must be positive integer.",
            )

        return tool.handler(value)


class Agent:
    """
    Coordinate observations, decision and tool execution.
    """

    def __init__(self, environment: Environment) -> None:
        """
        Connect the environment, decision policy, and tool execution.

        :param environment:
        """
        self.environment = environment
        self.policy = DecisionPolicy()
        self.executor = ToolExecutor(self.environment)


    def run(self, max_steps: int = 10) -> str:
        """
        Run until completion, tool failure or action limit.

        :param max_steps:
        :return:
        """
        if (
            not isinstance(max_steps, int)
            or isinstance(max_steps, bool)
            or max_steps < 1
        ):
            raise ValueError("Max step must be positive integer.")

        for step in range(1, max_steps + 1):
            observation = self.environment.observe()
            if observation.distance == 0:
                return "goal_reached"

            call = self.policy.decide(observation)
            result = self.executor.execute(call)
            print(f"Step {step}: {call.name} {call.arguments}")
            print(f"Result: {result.message}")

            if not result.success:
                return "tool_failed"

            after = self.environment.observe()
            print(
                f"  State: distance={after.distance}, "
                f"battery={after.battery}"
            )

            if after.distance == 0:
                return "goal_reached"

        return "step_limit_reached"

def main():
    environment = Environment()
    agent = Agent(environment)
    print("Agent Run: ")
    print("Final status: ", agent.run())

    # Demonstrate validation using a separate environment
    print("\nInvalid tool-call Example:")

    executor = ToolExecutor(Environment())
    invalid_call = ToolCall(
        name="move",
        arguments={"steps": -1},
    )
    result = executor.execute(invalid_call)
    print(result)

if __name__ == "__main__":
    main()
