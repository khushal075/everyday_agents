"""
22_model_routing_and_caching.py

Make the robot's decisions cheaper: try a small model first, escalate to a large
one only when needed, and reuse answers for states already seen.

Scenario:
    The same robot as examples 01-21, now making several trips. Each trip
    starts a few moves from the destination with some battery; the battery
    holds two units. Every step asks a model for the next action.

Goal:
    Reach every destination while spending as little model cost and time
    as possible, without accepting a single invalid action.

Difference from example 16:
    Example 16 used one model for every step. Here each step goes through
    a cache, then a small model, then a large model, stopping at the first
    one that gives a valid action.

Flow:
    For every decision:
        1. Cache: if this exact state was answered before, reuse that action.
        2. Small model: cheap and fast, but sometimes wrong.
        3. Validate: the same rule check as example 20.
        4. Large model: called only if the small model's answer is invalid.
        5. Store the validated action in the cache.
    At the end, compare the cost with calling the large model every time.

New concepts:
    1. Routing sends easy work to a cheap model and hard work to a strong one.
    2. Validation decides when to escalate, so routing never lowers quality.
    3. A cache returns the same answer for the same input at almost no cost.
    4. Only validated answers are cached, so a mistake is never repeated.
    5. The cache key includes a policy version: changing the rules or prompt
       makes old answers unusable instead of silently wrong.
    6. Validation checks that an action is safe, not that it is the best one.
       The small model's "recharge 1" is valid, so it is accepted and cached,
       even though recharging to full would need fewer steps.

Modes:
    1. --scripted                       Fixture models with assumed costs.
    2. --small <name> --large <name>    Two local Ollama models.

Scripted mode does not run models. The small fixture always tries to drive
straight to the destination; the large fixture follows the battery rules.
Costs and times in scripted mode are assumed numbers for illustration.

Requirements:
    Python's standard library. Model mode also needs a running Ollama server.
"""

import argparse
import json
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BATTERY_CAPACITY = 2

# Changing the rules or the prompt should change this, so old cache entries stop matching.
POLICY_VERSION = "v1"

TRIPS = [(3, 1), (3, 1), (4, 2), (3, 1), (5, 0)]

SYSTEM_PROMPT = " ".join([
    "You choose a robot's next action.",
    "Actions: move (each step uses one battery unit) and recharge (adds units).",
    f"The battery holds at most {BATTERY_CAPACITY} units.",
    'Reply with only JSON: {"action": "move" or "recharge", "amount": positive integer}.',
])


@dataclass(frozen=True)
class Observation:
    """
    The robot's remaining distance and battery.
    """
    distance: int
    battery: int

    def __str__(self) -> str:
        return f"distance {self.distance}, battery {self.battery}"


@dataclass(frozen=True)
class Action:
    """
    One proposed or validated action.
    """
    name: str
    amount: int


@dataclass(frozen=True)
class ModelAnswer:
    """
    What one model call returned, and what it cost.
    """
    action: Action | None
    cost: float
    seconds: float


class Decider(Protocol):
    """
    Anything that proposes the next action for a state.
    """

    name: str

    def decide(self, state: Observation) -> ModelAnswer:
        ...


class ActionValidator:
    """
    Check an action against the battery rules, as in example 20.
    """

    def check(self, action: Action | None, state: Observation) -> str | None:
        """
        :param action: The proposed action, or None if the reply was unreadable.
        :param state:  The current state.
        :return: Why the action is invalid, or None if it may run.
        """
        if action is None:
            return "unreadable reply"
        if action.name not in ("move", "recharge") or action.amount <= 0:
            return f"unknown action {action.name} {action.amount}"
        if action.name == "move" and action.amount > min(state.battery, state.distance):
            return f"move {action.amount} needs more battery or distance than is left"
        if action.name == "recharge" and state.battery + action.amount > BATTERY_CAPACITY:
            return f"recharge {action.amount} exceeds capacity"
        return None


class ScriptedSmallModel:
    """
    A cheap fixture that always tries to drive straight to the destination.
    """

    name = "small"

    def decide(self, state: Observation) -> ModelAnswer:
        """
        :param state: The current state.
        :return: move all remaining steps, or recharge 1 if the battery is empty.
        """
        if state.battery == 0:
            return ModelAnswer(Action("recharge", 1), cost=1, seconds=0.1)
        return ModelAnswer(Action("move", state.distance), cost=1, seconds=0.1)


class ScriptedLargeModel:
    """
    An expensive fixture that follows the battery rules.
    """

    name = "large"

    def decide(self, state: Observation) -> ModelAnswer:
        """
        :param state: The current state.
        :return: Recharge to full when empty, otherwise move as far as the battery allows.
        """
        if state.battery == 0:
            return ModelAnswer(Action("recharge", BATTERY_CAPACITY), cost=10, seconds=1.5)
        return ModelAnswer(Action("move", min(state.battery, state.distance)), cost=10, seconds=1.5)


class OllamaDecider:
    """
    Ask a local Ollama model for the next action and time the call.
    """

    def __init__(self, name: str, model: str, cost_per_call: float) -> None:
        """
        :param name:          Label used in the output, e.g. small or large.
        :param model:         An installed Ollama model.
        :param cost_per_call: An assumed price per call, for the cost report.
        """
        self.name = name
        self.model = model
        self.cost_per_call = cost_per_call

    def decide(self, state: Observation) -> ModelAnswer:
        """
        :param state: The current state.
        :return: The proposed action (None if unreadable), its cost and its time.
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Distance: {state.distance}. Battery: {state.battery}."},
            ],
            "stream": False,
            "format": "json",
        }
        request = Request(
            url="http://localhost:11434/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        started = time.perf_counter()
        with urlopen(request, timeout=120) as response:
            content = (json.load(response).get("message") or {}).get("content", "")
        seconds = time.perf_counter() - started

        try:
            reply = json.loads(content)
            amount = reply["amount"]
            action = Action(str(reply["action"]), amount) if isinstance(amount, int) and not isinstance(amount, bool) else None
        except (json.JSONDecodeError, KeyError, TypeError):
            action = None
        return ModelAnswer(action, cost=self.cost_per_call, seconds=seconds)


class Ledger:
    """
    Count calls, cost and time, so routing can be compared with a baseline.
    """

    def __init__(self) -> None:
        self.decisions = 0
        self.cache_hits = 0
        self.calls = {"small": 0, "large": 0}
        self.cost = 0.0
        self.seconds = 0.0
        self.large_cost_per_call = 0.0
        self.large_seconds_per_call = 0.0

    def record(self, decider: Decider, answer: ModelAnswer) -> None:
        """
        Add one model call to the totals.

        :param decider: Which model was called.
        :param answer:  Its cost and time.
        """
        self.calls[decider.name] += 1
        self.cost += answer.cost
        self.seconds += answer.seconds
        if decider.name == "large":
            self.large_cost_per_call = answer.cost
            self.large_seconds_per_call = answer.seconds

    def report(self) -> None:
        """
        Print the totals and the cost of calling the large model for every decision.

        :return: None.
        """
        print(f"\nDecisions: {self.decisions}")
        print(f"  cache hits:  {self.cache_hits}")
        print(f"  small calls: {self.calls['small']}")
        print(f"  large calls: {self.calls['large']}")
        print(f"Cost: {self.cost:g} (always large: {self.decisions * self.large_cost_per_call:g})")
        print(f"Model time: {self.seconds:.1f}s (always large: ~{self.decisions * self.large_seconds_per_call:.1f}s)")


class Router:
    """
    Answer from the cache, else the small model, else the large model.
    """

    def __init__(self, small: Decider, large: Decider, validator: ActionValidator, ledger: Ledger) -> None:
        """
        :param small:     Tried first.
        :param large:     Tried when the small answer is invalid.
        :param validator: Decides when to escalate.
        :param ledger:    Records every call.
        """
        self.small = small
        self.large = large
        self.validator = validator
        self.ledger = ledger
        self.cache: dict[tuple[int, int, str], Action] = {}

    def next_action(self, state: Observation) -> Action:
        """
        Return a validated action, printing the route it took.

        :param state: The current state.
        :return: An action that passed validation.
        """
        self.ledger.decisions += 1
        key = (state.distance, state.battery, POLICY_VERSION)

        if key in self.cache:
            self.ledger.cache_hits += 1
            action = self.cache[key]
            print(f"  {state}: cache -> {action.name} {action.amount}")
            return action

        route = []
        for decider in (self.small, self.large):
            answer = decider.decide(state)
            self.ledger.record(decider, answer)
            problem = self.validator.check(answer.action, state)
            proposed = f"{answer.action.name} {answer.action.amount}" if answer.action else "?"
            if problem is None:
                route.append(f"{decider.name}: {proposed}")
                print(f"  {state}: {' -> '.join(route)}")
                self.cache[key] = answer.action
                return answer.action
            route.append(f"{decider.name}: {proposed} (rejected: {problem})")

        raise ValueError(f"No model gave a valid action for {state}: {' -> '.join(route)}")


class Fleet:
    """
    Run every trip with the router choosing each action.
    """

    def __init__(self, router: Router) -> None:
        """
        :param router: Chooses each action.
        """
        self.router = router

    def run(self, trips: list[tuple[int, int]], max_steps: int = 10) -> None:
        """
        Drive each trip to its destination.

        :param trips:     Starting (distance, battery) pairs.
        :param max_steps: Stop a trip that takes longer than this.
        :return: None.
        """
        for number, (distance, battery) in enumerate(trips, start=1):
            print(f"Trip {number}: distance {distance}, battery {battery}")
            for _ in range(max_steps):
                if distance == 0:
                    break
                action = self.router.next_action(Observation(distance, battery))
                if action.name == "move":
                    distance -= action.amount
                    battery -= action.amount
                else:
                    battery += action.amount


def main() -> None:
    """
    Run several trips through the cache and the two model tiers.

    :return: None.
    """
    parser = argparse.ArgumentParser(description="Route decisions between a small and a large model, with a cache.")
    parser.add_argument("--scripted", action="store_true", help="Use fixture models with assumed costs.")
    parser.add_argument("--small", help="A small installed Ollama model.")
    parser.add_argument("--large", help="A large installed Ollama model.")
    args = parser.parse_args()

    if args.scripted and (args.small or args.large):
        parser.error("Use either --scripted, or both --small and --large.")
    if not args.scripted and not (args.small and args.large):
        parser.error("Use either --scripted, or both --small and --large.")

    small: Decider = OllamaDecider("small", args.small, 1) if args.small else ScriptedSmallModel()
    large: Decider = OllamaDecider("large", args.large, 10) if args.large else ScriptedLargeModel()
    ledger = Ledger()
    fleet = Fleet(Router(small=small, large=large, validator=ActionValidator(), ledger=ledger))

    try:
        fleet.run(TRIPS)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        parser.exit(1, f"Ollama HTTP {error.code}: {detail}\n")
    except (URLError, TimeoutError, ValueError) as error:
        parser.exit(1, f"Could not finish the trips: {error}\n")

    ledger.report()


if __name__ == "__main__":
    # Example commands:
    #   uv run python 22_model_routing_and_caching.py --scripted
    #   ollama pull qwen2.5:3b
    #   uv run python 22_model_routing_and_caching.py --small qwen2.5:3b --large qwen
    main()
