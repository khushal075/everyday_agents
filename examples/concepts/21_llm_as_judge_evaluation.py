"""
21_llm_as_judge_evaluation.py

Grade the robot's trip plans and their explanations, and check the graders too.

Scenario:
    The same robot as examples 01-20: three moves from the destination,
    one battery unit, a battery that holds two. Example 17 asked a model for
    a plan and a reason. Here five such answers are graded.

Goal:
    Decide which answers are good, using the cheapest grader that can be
    trusted for each part of the answer.

Difference from example 15:
    Example 15 compared decisions with one expected value. That breaks when
    several answers are right, and it cannot grade free text at all.

Flow:
    1. Grade each plan two ways:
        - Exact match against one reference plan.
        - Simulation: run the plan and check that it reaches the destination.
    2. Grade each explanation with a judge, because code cannot easily
       tell whether a sentence is true.
    3. Compare every grader with labels a person wrote, and report agreement.

New concepts:
    1. Exact match marks a different but valid answer as wrong.
    2. When code can check the outcome (simulation), prefer it: it is cheap,
       fast and does not change between runs.
    3. An LLM judge grades what code cannot, using a written rubric.
    4. A judge can be wrong too, so measure its agreement with human labels
       before trusting it.
    5. The judge must reply in a fixed format; an unreadable verdict is
       counted as an error, not guessed.

Modes:
    1. --scripted          A keyword rule stands in for the judge.
    2. --model <name>      A local Ollama model is the judge.

The scripted judge is not a model. It flags explanations that state a
wrong capacity or are too short, and it misses subtler mistakes on purpose.

Requirements:
    Python's standard library. Model mode also needs a running Ollama server.
"""

import argparse
import json
import re
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

Verdict = Literal["correct", "incorrect", "error"]

BATTERY_CAPACITY = 2
START_DISTANCE = 3
START_BATTERY = 1

REFERENCE_PLAN = (("move", 1), ("recharge", 2), ("move", 2))

RUBRIC = " ".join([
    f"A robot starts {START_DISTANCE} steps from its destination with {START_BATTERY} battery unit.",
    f"The battery holds at most {BATTERY_CAPACITY} units. Each move step uses one unit.",
    "You are given a plan and an explanation of it.",
    "The explanation is correct only if every statement in it is true for these rules and this plan.",
    'Reply with only JSON: {"verdict": "correct" or "incorrect", "why": "one short sentence"}.',
])


@dataclass(frozen=True)
class Case:
    """
    One answer to grade, with labels a person wrote.
    """
    name: str
    plan: tuple[tuple[str, int], ...]
    explanation: str
    human_plan_ok: bool
    human_explanation_ok: bool


CASES = [
    Case("reference", (("move", 1), ("recharge", 2), ("move", 2)),
         "Use the 1 unit, recharge to the full 2 units, then move the last 2 steps.", True, True),
    Case("different but valid", (("recharge", 1), ("move", 2), ("recharge", 1), ("move", 1)),
         "Top up to 2 units, move 2, top up again, then move the final step.", True, True),
    Case("wrong fact", (("move", 1), ("recharge", 2), ("move", 2)),
         "The battery holds 3 units, so one recharge is plenty.", True, False),
    Case("broken plan", (("recharge", 1), ("move", 3)),
         "Recharge, then go.", False, False),
    Case("subtle mistake", (("move", 1), ("recharge", 2), ("move", 2)),
         "Move until the battery is empty, recharge twice, then finish.", True, False),
]


class Judge(Protocol):
    """
    Anything that grades an explanation of a plan.
    """

    def grade(self, case: Case) -> Verdict:
        ...


class ExactMatchGrader:
    """
    Pass a plan only if it equals the reference plan.
    """

    def grade(self, case: Case) -> bool:
        """
        :param case: The answer to grade.
        :return: True if the plan is identical to REFERENCE_PLAN.
        """
        return case.plan == REFERENCE_PLAN


class SimulationGrader:
    """
    Pass a plan if running it reaches the destination without breaking a rule.
    """

    def grade(self, case: Case) -> bool:
        """
        Run the plan on a copy of the starting state, as in example 17.

        :param case: The answer to grade.
        :return: True if every action is possible and the robot arrives.
        """
        distance, battery = START_DISTANCE, START_BATTERY
        for action, amount in case.plan:
            if action == "move":
                if amount > battery or amount > distance:
                    return False
                distance -= amount
                battery -= amount
            elif action == "recharge":
                if battery + amount > BATTERY_CAPACITY:
                    return False
                battery += amount
            else:
                return False
        return distance == 0


class KeywordJudge:
    """
    Stand in for a model judge with two simple rules.

    It catches a wrong capacity and very short explanations, but not
    a wrong count such as "recharge twice".
    """

    def grade(self, case: Case) -> Verdict:
        """
        :param case: The answer whose explanation is graded.
        :return: correct or incorrect.
        """
        text = case.explanation.lower()
        stated_capacities = re.findall(r"holds (\d+) units", text)
        if any(int(number) != BATTERY_CAPACITY for number in stated_capacities):
            return "incorrect"
        if len(text.split()) < 4:
            return "incorrect"
        return "correct"


class OllamaJudge:
    """
    Ask a local Ollama model to grade an explanation against the rubric.
    """

    def __init__(self, model: str) -> None:
        """
        Store the installed model name.

        :param model: An installed Ollama model.
        """
        self.model = model

    def grade(self, case: Case) -> Verdict:
        """
        Send the rubric, plan and explanation; read a fixed-format verdict.

        :param case: The answer whose explanation is graded.
        :return: correct, incorrect, or error if the reply cannot be read.
        """
        plan_text = ", ".join(f"{action} {amount}" for action, amount in case.plan)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": RUBRIC},
                {"role": "user", "content": f"Plan: {plan_text}\nExplanation: {case.explanation}"},
            ],
            "stream": False,
            "format": "json",
            # Temperature 0 makes the same question get the same verdict.
            "options": {"temperature": 0},
        }
        request = Request(
            url="http://localhost:11434/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=120) as response:
            content = (json.load(response).get("message") or {}).get("content", "")

        try:
            verdict = json.loads(content).get("verdict")
        except (json.JSONDecodeError, AttributeError):
            return "error"
        return verdict if verdict in ("correct", "incorrect") else "error"


class Evaluation:
    """
    Run every grader on every case and compare them with the human labels.
    """

    def __init__(self, exact: ExactMatchGrader, simulation: SimulationGrader, judge: Judge) -> None:
        """
        Store the graders.

        :param exact:      Compares plans with one reference.
        :param simulation: Runs plans.
        :param judge:      Grades explanations.
        """
        self.exact = exact
        self.simulation = simulation
        self.judge = judge

    def run(self, cases: list[Case]) -> None:
        """
        Print one row per case, then each grader's agreement with people.

        :param cases: The answers to grade.
        :return: None.
        """
        agree = {"exact match": 0, "simulation": 0, "judge": 0}
        print(f"{'case':<20} {'exact':<7} {'simulate':<9} {'judge':<10} human (plan / explanation)")

        for case in cases:
            exact_ok = self.exact.grade(case)
            simulated_ok = self.simulation.grade(case)
            verdict = self.judge.grade(case)

            agree["exact match"] += exact_ok == case.human_plan_ok
            agree["simulation"] += simulated_ok == case.human_plan_ok
            agree["judge"] += verdict == ("correct" if case.human_explanation_ok else "incorrect")

            human = f"{'ok' if case.human_plan_ok else 'bad'} / {'ok' if case.human_explanation_ok else 'bad'}"
            print(
                f"{case.name:<20} {'pass' if exact_ok else 'fail':<7} "
                f"{'pass' if simulated_ok else 'fail':<9} {verdict:<10} {human}"
            )

        print("\nAgreement with human labels:")
        for grader, count in agree.items():
            print(f"  {grader:<12} {count}/{len(cases)}")


def main() -> None:
    """
    Grade the five answers with a scripted or a model judge.

    :return: None.
    """
    parser = argparse.ArgumentParser(description="Grade plans and explanations, and grade the graders.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scripted", action="store_true", help="Use the keyword judge.")
    mode.add_argument("--model", help="An installed Ollama model to use as the judge.")
    args = parser.parse_args()

    judge: Judge = OllamaJudge(args.model) if args.model else KeywordJudge()
    evaluation = Evaluation(exact=ExactMatchGrader(), simulation=SimulationGrader(), judge=judge)

    try:
        evaluation.run(CASES)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        parser.exit(1, f"Ollama HTTP {error.code}: {detail}\n")
    except (URLError, TimeoutError) as error:
        parser.exit(1, f"Could not run the judge: {error}\n")


if __name__ == "__main__":
    # Example commands:
    #   uv run python 21_llm_as_judge_evaluation.py --scripted
    #   uv run python 21_llm_as_judge_evaluation.py --model qwen
    main()
