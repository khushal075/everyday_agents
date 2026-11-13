"""
10_planning_and_replanning.py

Find a route  through a building, then revise it when a move fails.

Uses only the python standard library.
The building is simulated.
The planner searches a map; no LLM or trained model is needed.
"""

from collections import deque
from typing import Literal

Status = Literal["goal_reached", "no_route", "step_limit_reached"]

BUILDING: dict[str, tuple[str, ...]] = {
    "A": ("B", "C"),
    "B": ("A", "D"),
    "C": ("A", "E"),
    "D": ("B", "E"),
    "E": ("C", "D"),
}

class Environment:
    """
    Track the robot's location and enforce actual passage closures.
    """
    def __init__(self) -> None:
        """
        Start in Room A with the B-D passage closed.
        """
        self.location = 'A'
        self.closed_passage = {frozenset({"B", "D"})}

    def move(self, destination: str) -> bool:
        """
        Move to an adjacent room, or return False if the passage is closed.

        :param destination:
        :return:
        """
        if destination not in BUILDING[self.location]:
            raise ValueError(f"Destination {destination} is not adjacent to {self.location}")

        if frozenset({self.location, destination}) in self.closed_passage:
            return False

        self.location = destination
        return True


class Planner:
    """
    Find the shortest route using the map and known closures.
    """

    def plan(
            self,
            start: str,
            goal: str,
            known_closed: set[frozenset[str]],
    ) -> list[str] | None:
        """
        Return the route including start and goal, or None if unreachable.

        :param start:
        :param goal:
        :param known_closed:
        :return:
        """
        # Breath-first search checks shorter routes before longer one.
        routes = deque([[start]])
        visited = {start}

        while routes:
            route = routes.popleft()
            current = route[-1]
            if current == goal:
                return route
            for neighbor in BUILDING[current]:
                passage = frozenset({current, neighbor})
                if neighbor not in visited and passage not in known_closed:
                    visited.add(neighbor)
                    routes.append([*route, neighbor])
        return None

class Agent:
    """
    Follow a plan and revise it when the environment blocks a move.
    """
    def __init__(self, environment: Environment, planner: Planner) -> None:
        """
        Connect the move tool and start with no known closures.
        :param environment:
        :param planner:
        """
        self.environment = environment
        self.planner = planner
        self.known_closed: set[frozenset[str]] = set()

    def run(self, goal: str, max_attempts: int = 10) -> Status:
        """
        Reach the goal, report no route, or stop at move limit.

        :param goal:
        :param max_attempts:
        :return:
        """
        if goal not in BUILDING:
            raise ValueError(f"Unknown room: {goal}")
        if max_attempts < 1:
            raise ValueError(f"Max attempts must be positive integer")

        remaining: deque[str] = deque()
        for _ in range(max_attempts):
            current = self.environment.location
            if current == goal:
                return "goal_reached"

            if not remaining:
                route = self.planner.plan(current, goal, self.known_closed)
                if route is None:
                    return "no_route"

                print("Plan:", " → ".join(route))
                remaining.extend(route[1:]) # Skip the room we are already in.

            destination = remaining.popleft()
            if not self.environment.move(destination):
                print(f"Blocked: {current} → {destination}. Replanning.")
                self.known_closed.add(frozenset({current, destination}))
                remaining.clear()
                continue

            if self.environment.location == goal:
                return "goal_reached"

        return "step_limit_reached"

def main() -> None:
    """
    Run the robot and show how its route changes.
    """
    agent = Agent(Environment(), Planner())
    print("Final status:", agent.run(goal="D"))


if __name__ == "__main__":
    main()
