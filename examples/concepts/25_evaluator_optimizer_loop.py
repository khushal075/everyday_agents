"""
25_evaluator_optimizer_loop.py

Improve a trip plan round by round: generate, critique, revise, and stop
when it is good enough.

Scenario:
    The same robot as examples 01-24: three moves from the destination,
    one battery unit, a battery that holds two.

Goal:
    Not just a plan that works, but a good plan: as few actions as possible,
    with a short, clear reason.

Difference from examples 17 and 21:
    Example 17 repaired plans until they were valid.
    Example 21 graded answers that already existed.
    Here a valid plan is only the start: an evaluator scores it against
    several criteria, and the generator keeps improving it.

Flow:
    1. The generator proposes a plan and a reason.
    2. The evaluator checks each criterion and writes feedback for failures:
        - works: the plan reaches the destination (simulated).
        - shortest: it uses the fewest actions possible (found by search).
        - concise: the reason is at most 15 words.
    3. The feedback goes back to the generator for the next round.
    4. Stop when every criterion is met, or after the round limit.
    5. Return the best plan seen, not simply the last one.

New concepts:
    1. Separating the generator from the evaluator: one writes, one judges.
    2. Criteria are written down in advance, so "good enough" is clear.
    3. Code checks what it can (works, shortest); a word count stands in
       for quality checks that might need a model judge (example 21).
    4. A revision can be worse than the one before, so keep the best so far.
    5. A round limit bounds the cost of improving.

Modes:
    1. --scripted        Fixture plans: valid but long, then broken, then best.
    2. --model <name>    A local Ollama model generates and revises.

Requirements:
    Python's standard library. Model mode also needs a running Ollama server.
"""

import argparse
import json
from collections import deque
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BATTERY_CAPACITY = 2
START = (3, 1)  # distance, battery
MAX_REASON_WORDS = 15

TASK = (
    f"A robot is {START[0]} steps from its destination with {START[1]} battery unit. "
    f"The battery holds at most {BATTERY_CAPACITY} units; each move step uses one unit. "
    'Reply with only JSON: {"actions": [{"action": "move" or "recharge", "amount": integer}], '
    '"reason": "short sentence"}.'
)


@dataclass(frozen=True)
class Review:
    """
    The evaluator's verdict on one proposal.
    """
    passed: tuple[str, ...]
    feedback: tuple[str, ...]

    @property
    def rank(self) -> tuple[bool, int]:
        """Rank working plans ahead of invalid ones, then compare passed criteria."""
        return ("works" in self.passed, self.score)

    @property
    def score(self) -> int:
        """
        :return: How many criteria passed.
        """
        return len(self.passed)


class Generator(Protocol):
    """
    Anything that proposes a plan, given feedback on the last one.
    """

    def propose(self, feedback: list[str]) -> str:
        ...


class ScriptedGenerator:
    """
    Return fixed proposals: valid but long, then broken, then the best plan.
    """

    PROPOSALS = [
        {"actions": [{"action": "move", "amount": 1}, {"action": "recharge", "amount": 1},
                     {"action": "move", "amount": 1}, {"action": "recharge", "amount": 1},
                     {"action": "move", "amount": 1}],
         "reason": "Move one step at a time and recharge a little each time, so the battery never runs out."},
        {"actions": [{"action": "move", "amount": 3}],
         "reason": "Go straight there."},
        {"actions": [{"action": "move", "amount": 1}, {"action": "recharge", "amount": 2},
                     {"action": "move", "amount": 2}],
         "reason": "Use the one unit, recharge to full, then move the last two steps."},
    ]

    def __init__(self) -> None:
        self.round = 0

    def propose(self, feedback: list[str]) -> str:
        """
        :param feedback: Ignored by the fixture.
        :return: The next fixed proposal as JSON text.
        """
        proposal = self.PROPOSALS[min(self.round, len(self.PROPOSALS) - 1)]
        self.round += 1
        return json.dumps(proposal)


class OllamaGenerator:
    """
    Ask a local Ollama model for a plan, sending the feedback from the last round.
    """

    def __init__(self, model: str) -> None:
        """
        :param model: An installed Ollama model.
        """
        self.model = model
        self.messages: list[dict] = [{"role": "user", "content": TASK}]

    def propose(self, feedback: list[str]) -> str:
        """
        :param feedback: What the evaluator said about the last proposal.
        :return: The model's reply text.
        """
        if feedback:
            self.messages.append({"role": "user", "content": (
                "Improve your plan:\n" + "\n".join(f"- {item}" for item in feedback)
                + "\nReply with only the JSON."
            )})
        payload = {"model": self.model, "messages": self.messages, "stream": False, "format": "json"}
        request = Request(
            url="http://localhost:11434/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=120) as response:
            reply = (json.load(response).get("message") or {}).get("content", "")
        self.messages.append({"role": "assistant", "content": reply})
        return reply


class Evaluator:
    """
    Score a proposal against three criteria and explain each failure.
    """

    def __init__(self) -> None:
        self.fewest_actions = self.shortest_plan_length()

    @staticmethod
    def shortest_plan_length() -> int:
        """
        Search every possible plan, shortest first, and return the fewest actions needed.

        :return: The length of the shortest working plan.
        """
        queue = deque([(START, 0)])
        seen = {START}
        while queue:
            (distance, battery), length = queue.popleft()
            if distance == 0:
                return length
            options = [(distance - k, battery - k) for k in range(1, min(battery, distance) + 1)]
            options += [(distance, battery + u) for u in range(1, BATTERY_CAPACITY - battery + 1)]
            for option in options:
                if option not in seen:
                    seen.add(option)
                    queue.append((option, length + 1))
        raise ValueError("No plan reaches the destination.")

    @staticmethod
    def works(actions: list) -> str | None:
        """
        Simulate the plan from START.

        :param actions: The proposed actions.
        :return: Why it fails, or None if it reaches the destination.
        """
        distance, battery = START
        for number, step in enumerate(actions, start=1):
            amount = step.get("amount") if isinstance(step, dict) else None
            if not isinstance(amount, int) or isinstance(amount, bool):
                return f"Action {number} must be an object with an integer amount."
            action = step.get("action")
            if action == "move" and 0 < amount <= min(battery, distance):
                distance, battery = distance - amount, battery - amount
            elif action == "recharge" and 0 < amount <= BATTERY_CAPACITY - battery:
                battery += amount
            else:
                return f"Action {number} ({action} {amount}) is not possible with battery {battery}."
        return None if distance == 0 else f"The plan ends {distance} step(s) short."

    def review(self, reply: str) -> Review:
        """
        Check every criterion and collect feedback for the ones that fail.

        :param reply: The generator's JSON text.
        :return: Which criteria passed, and feedback for the rest.
        """
        try:
            proposal = json.loads(reply)
            actions, reason = proposal["actions"], proposal["reason"]
            if not isinstance(actions, list) or not isinstance(reason, str):
                raise TypeError
        except (json.JSONDecodeError, KeyError, TypeError):
            return Review(passed=(), feedback=("Reply with JSON containing 'actions' (a list) and 'reason'.",))

        passed, feedback = [], []
        problem = self.works(actions)
        if problem is None:
            passed.append("works")
            if len(actions) == self.fewest_actions:
                passed.append("shortest")
            else:
                feedback.append(f"It uses {len(actions)} actions; {self.fewest_actions} is possible. "
                                "Recharge more at once.")
        else:
            feedback.append(problem)

        words = len(reason.split())
        if 0 < words <= MAX_REASON_WORDS:
            passed.append("concise")
        else:
            feedback.append(f"The reason has {words} words; use at most {MAX_REASON_WORDS}.")

        return Review(passed=tuple(passed), feedback=tuple(feedback))


class Optimizer:
    """
    Run generate-review rounds and keep the best proposal.
    """

    CRITERIA = 3

    def __init__(self, generator: Generator, evaluator: Evaluator) -> None:
        """
        :param generator: Writes proposals.
        :param evaluator: Judges them.
        """
        self.generator = generator
        self.evaluator = evaluator

    def run(self, max_rounds: int) -> tuple[str, Review]:
        """
        Improve until every criterion passes or the rounds run out.

        :param max_rounds: The most rounds to run.
        :return: The best proposal and its review.
        """
        best: tuple[str, Review] | None = None
        feedback: list[str] = []

        for round_number in range(1, max_rounds + 1):
            reply = self.generator.propose(feedback)
            review = self.evaluator.review(reply)
            print(f"Round {round_number}: score {review.score}/{self.CRITERIA}, passed {list(review.passed)}")
            print(f"  {reply}")
            for item in review.feedback:
                print(f"  Feedback: {item}")

            if best is None or review.rank > best[1].rank:
                best = (reply, review)
            else:
                print("  Not better than the best so far; keeping the earlier plan.")

            if review.score == self.CRITERIA:
                print("  All criteria met; stopping.")
                break
            feedback = list(review.feedback)

        assert best is not None
        return best


def main() -> None:
    """
    Improve one plan with a scripted or a model generator.

    :return: None.
    """
    parser = argparse.ArgumentParser(description="Generate, critique, and revise a plan.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scripted", action="store_true", help="Use fixture proposals.")
    mode.add_argument("--model", help="An installed Ollama model generates the plans.")
    parser.add_argument("--max-rounds", type=int, default=4)
    args = parser.parse_args()

    if args.max_rounds < 1:
        parser.error("--max-rounds must be at least 1.")

    generator: Generator = OllamaGenerator(args.model) if args.model else ScriptedGenerator()
    evaluator = Evaluator()
    print(f"Fewest possible actions: {evaluator.fewest_actions}\n")

    try:
        reply, review = Optimizer(generator, evaluator).run(args.max_rounds)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        parser.exit(1, f"Ollama HTTP {error.code}: {detail}\n")
    except (URLError, TimeoutError) as error:
        parser.exit(1, f"Could not run the model: {error}\n")

    print(f"\nBest plan (score {review.score}/{Optimizer.CRITERIA}): {reply}")


if __name__ == "__main__":
    # Example commands:
    #   uv run python 25_evaluator_optimizer_loop.py --scripted
    #   uv run python 25_evaluator_optimizer_loop.py --scripted --max-rounds 2
    #   uv run python 25_evaluator_optimizer_loop.py --model qwen
    main()
