"""
02_ml_powered_agent.py

Demonstrate an agent whose action selection policy is learned from data.

Goal:
    Reach a destination while managing a limited battery.

Difference from example 01
    A trained decision tree replaces handwritten action selection rule.

Requirements:
    Python and Scikit-learn.

Everything is simulated. These tiny training examples demonstrate the
mechanism; they do not establish a reliable real-world robot controller.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypedDict, cast, List
from sklearn.tree import DecisionTreeClassifier

# Data Types
@dataclass(frozen=True)
class Observation:
    """
    Sensor information available to Agent.
    """
    distance: int
    battery: int

Action = Literal["move", "recharge"]

RunStatus = Literal["goal_reached", "action_rejected", "action_failed", "step_limit_reached"]


class Environment:
    """
    Simulate the robot's surroundings, observations, and tools.
    """

    def __init__(self):
        """
        Start three moves away with one battery unit.
        """
        self.distance = 3
        self.battery = 1

    def observe(self) -> Observation:
        """
        Return the current state of distance and battery.
        :return:
        """
        return Observation(
            distance=self.distance,
            battery= self.battery
        )

    def move(self) -> None:
        """
        Move 1 step and consume 1 battery.

        :return:

        Raises:
            RuntimeError: If the destination is reached or battery is empty.
        """
        if self.distance <= 0:
            raise RuntimeError("The distance has already been reached.")

        if self.battery <= 0:
            raise RuntimeError("Cannot move with an empty battery.")

        self.distance -= 1
        self.battery -= 1

    def recharge(self) -> None:
        self.battery = 2


def train_model() -> DecisionTreeClassifier:
    """
    Train an action-selection model from labeled observations.

    Each training input is [distance, battery].
    Each target is an action name.
    :return:
    """

    observations: List[List[int]] = [
        [1, 0], [2, 0], [3, 0],
        [1, 1], [2, 1], [3, 1],
        [1, 2], [2, 2], [3, 2]
    ]

    actions: List[Action] = [
        "recharge", "recharge", "recharge",
        "move", "move", "move",
        "move", "move", "move"
    ]

    model = DecisionTreeClassifier(
        max_depth=1,
        random_state=42
    )
    model.fit(observations, actions)
    return model

class Agent:
    """
    Coordinate a learned decision policy and environment tools.
    """

    def __init__(
            self,
            environment: Environment,
            model: DecisionTreeClassifier
    ) -> None:
        """
        Connect the environment, trained model and tool registry.

        :param environment:
        :param model:
        """
        self.environment = environment
        self.model = model

        # Each tool take no argument and return no value
        self.tools: dict[Action, Callable[[], None]] = {
            "move": environment.move,
            "recharge": environment.recharge,
        }

    def choose_action(self, observation: Observation) -> Action:
        """
        Predict and validate an action from the current observation.

        :param observation:
        :return:

        Raises:
            ValueError: If model returns an unsupported action.
        """
        features: List[List[int]] = [
            [observation.distance, observation.battery]
        ]

        prediction = str(self.model.predict(features)[0])

        # Type hints do not validate model output, so check it explicitly.
        if prediction not in {"move", "recharge"}:
            raise ValueError(f"Unsupported model action: {prediction}")

        # The runtime check above establishes the allowed values.
        return cast(Action, prediction)


    def run(self, max_steps: int = 10) -> RunStatus:
        """
        Execute a bounded agent loop and return its termination status.

        Args:
            max_steps: Maximum number of actions permitted.


        Raises:
            ValueError: If max_steps is negative.

        :return:
        """
        if (
            not isinstance(max_steps, int)
            or isinstance(max_steps, bool)
            or max_steps < 1
        ):
            raise ValueError("max_steps must be a positive integer.")

        for step in range(1, max_steps + 1):
            observation = self.environment.observe()
            if observation.distance == 0:
                return "goal_reached"

            try:
                action = self.choose_action(observation)
            except ValueError as error:
                print(f"Action rejected: {error}")
                return "action_rejected"

            try:
                self.tools[action]()
            except RuntimeError as error:
                print(f"Action failed: {error}")
                return "action_failed"

            after = self.environment.observe()
            print(
                f"Step {step}: (distance={observation.distance}, battery={observation.battery}) → "
                f"| {action} | → "
                f"(distance={after.distance}, "
                f"battery={after.battery})"
            )
            if after.distance == 0:
                return "goal_reached"

        return "step_limit_reached"


def main():
    model = train_model()
    environment = Environment()
    agent = Agent(environment, model)

    result: RunStatus = agent.run()
    print(f"Final result: {result}")


if __name__ == "__main__":
    main()
