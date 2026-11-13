"""
01_rule_based_agent.py

Demonstrate a simple rule based Agent in simulated environment.

Goal:
    Reach a destination three moves away.

Behaviour:
    - Observe distance and battery.
    - Recharge when battery is empty.
    - Otherwise, move one step towards the destination.
    - Stop when the destination is reached or the step limit is exhausted.

This example uses Handwritten rules, not ML or LLM.
"""

class Environment:
    """
    Simulate the robot's surroundings, sensor readings, and actions etc.
    """


    def __init__(self):
        """
        Start three moves from destination with one battery unit.
        """
        self.distance = 3
        self.battery = 1

    def observe(self):
        """
        Return the current distance and battery as a new observation.

        :return:
        """
        return {
            "distance": self.distance,
            "battery": self.battery
        }

    def move(self):
        """
            1. Move one step.
            2. Consume one battery unit (Required to move one step)
        :return:
        """
        if self.distance <= 0:
            raise RuntimeError("Distance has already been reached.")

        if self.battery <= 0:
            raise RuntimeError("Cannot move with an empty battery.")

        self.distance -= 1
        self.battery -= 1

    def recharge(self):
        """
        Restore battery to its capacity of 2 units.
        :return:
        """
        self.battery = 2



class Agent:
    """
        Choose and execute actions towards a goal in an environment.
    """

    def __init__(self, environment):
        self.environment = environment
        self.tools = {
            "move": environment.move,
            "recharge": environment.recharge,
        }

    def choose_actions(self, observation):
        """
        Select the next action using deterministic detection policy.

        :param observation:
        :return:

        The agent checks the goal completion before calling this function.
        """

        if observation["battery"] == 0:
            return "recharge"
        return "move"

    def run(self, max_step = 10):
        """
        Observe, decide, and act until completion or the action limit.

        :param max_step:
        :return:

        """
        for _ in range(max_step):
            observation = self.environment.observe()

            if observation["distance"] == 0:
                return "goal_reached"

            action = self.choose_actions(observation)
            self.tools[action]()

            if observation["distance"] == 0:
                return "goal_reached"

        return "step_limit_reached"


def main():
    environment = Environment()
    agent = Agent(environment)
    result = agent.run()
    print("Final status:", result)


if __name__ == "__main__":
    main()
