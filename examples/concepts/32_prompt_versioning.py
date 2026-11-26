"""
32_prompt_versioning.py

Compare a new prompt with the current one on the same test cases before switching.

Scenario:
    The same robot as examples 01-31. The prompt that tells the model how to
    choose the next action has been reworded to fix a known problem. Before
    the new wording goes live, it must prove it is better and breaks nothing
    important.

Goal:
    Switch prompts only when the evidence says it is safe to.

Difference from examples 15 and 21:
    Example 15 caught a rule change with fixed test cases. Example 21 graded
    answers. Here two versions of a prompt are run on the same cases, side by
    side, and a release gate decides whether the new one replaces the old one.

Flow:
    1. Every prompt has a version name and a short fingerprint of its text,
       so results always say exactly which wording produced them.
    2. Run the current prompt and the candidate on the same test cases.
    3. Grade every answer: it must be valid, and move as far as the battery
       allows (or recharge when empty).
    4. Compare case by case: which cases improved, which regressed.
    5. Release gate: promote the candidate only if it scores at least as well
       and does not regress any critical case.

New concepts:
    1. A prompt is code: version it, and test it before changing it.
    2. Compare on the same cases, so a difference comes from the prompt alone.
    3. A better total score can still hide a regression.
    4. Critical cases must never get worse, whatever the total.
    5. The fingerprint changes whenever the text changes, even by one word.

Modes:
    --candidate v2    Better overall, but breaks a critical case: not promoted.
    --candidate v3    Fixes that too: promoted.
    Add --model <name> to run the prompts on a local Ollama model instead of
    the fixture.

The fixture is not a model. It returns the answers each prompt version is
known to produce, so the comparison can be seen without a model.

Requirements:
    Python's standard library. Model mode also needs a running Ollama server.
"""

import argparse
import hashlib
import json
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BATTERY_CAPACITY = 2

BASE = (
    "You choose a robot's next action. Each move step uses one battery unit; "
    f"the battery holds {BATTERY_CAPACITY}. "
    'Reply with only JSON: {"action": "move" or "recharge", "amount": integer}. '
)
PROMPTS = {
    "v1": BASE + "Move one step at a time.",
    "v2": BASE + "Move as far as the battery allows. Recharge to full when it is empty.",
    "v3": BASE + "Move as far as the battery allows, but never past the destination. "
                 "Recharge to full when it is empty.",
}


@dataclass(frozen=True)
class Case:
    """
    One robot state to test, and whether it is critical.
    """
    distance: int
    battery: int
    critical: bool = False

    def __str__(self) -> str:
        return f"distance {self.distance}, battery {self.battery}"


CASES = [
    Case(3, 1),
    Case(2, 0),
    Case(2, 2),
    Case(1, 1, critical=True),  # The last step: overshooting here strands the robot.
    Case(1, 0),
    Case(3, 2),
]


class Model(Protocol):
    """
    Anything that answers a prompt for a robot state.
    """

    def decide(self, version: str, prompt: str, case: Case) -> object:
        ...


class FixtureModel:
    """
    Return the answers each prompt version is known to produce.
    """

    def decide(self, version: str, prompt: str, case: Case) -> object:
        """
        :param version: Which prompt is being used.
        :param prompt:  Ignored by the fixture.
        :param case:    The robot state.
        :return: The parsed answer.
        """
        if case.battery == 0:
            return {"action": "recharge", "amount": BATTERY_CAPACITY}
        if version == "v1":
            return {"action": "move", "amount": 1}
        if version == "v2" and case.distance == 1:
            # "As far as the battery allows" makes it overshoot the last step.
            return {"action": "move", "amount": case.battery + 1}
        return {"action": "move", "amount": min(case.battery, case.distance)}


class OllamaModel:
    """
    Run the prompt on a local Ollama model.
    """

    def __init__(self, model: str) -> None:
        """
        :param model: An installed Ollama model.
        """
        self.model = model

    def decide(self, version: str, prompt: str, case: Case) -> object:
        """
        :return: The parsed answer, or None if it was not JSON.
        """
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": prompt},
                         {"role": "user", "content": f"Distance: {case.distance}. Battery: {case.battery}."}],
            "stream": False,
            "format": "json",
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
            return json.loads(content)
        except json.JSONDecodeError:
            return None


class Grader:
    """
    Decide whether one answer is right for its case.
    """

    def passes(self, answer: object, case: Case) -> bool:
        """
        :param answer: The parsed model answer.
        :param case:   The robot state.
        :return: True if valid, and it recharges when empty or moves as far as possible.
        """
        if not isinstance(answer, dict):
            return False
        action, amount = answer.get("action"), answer.get("amount")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            return False
        if case.battery == 0:
            return action == "recharge" and amount <= BATTERY_CAPACITY
        return action == "move" and amount == min(case.battery, case.distance)


class PromptComparison:
    """
    Run two prompt versions on the same cases and apply the release gate.
    """

    def __init__(self, model: Model, grader: Grader) -> None:
        """
        :param model:  Answers the prompts.
        :param grader: Grades each answer.
        """
        self.model = model
        self.grader = grader

    @staticmethod
    def fingerprint(text: str) -> str:
        """
        :param text: A prompt.
        :return: The first 8 characters of its SHA-256 hash.
        """
        return hashlib.sha256(text.encode()).hexdigest()[:8]

    def run(self, version: str) -> list[bool]:
        """
        :param version: The prompt version to test.
        :return: Pass or fail for each case, in order.
        """
        prompt = PROMPTS[version]
        return [self.grader.passes(self.model.decide(version, prompt, case), case) for case in CASES]

    def compare(self, baseline: str, candidate: str) -> bool:
        """
        Print both versions side by side, then decide.

        :param baseline:  The prompt in use now.
        :param candidate: The proposed replacement.
        :return: True if the candidate should be promoted.
        """
        for version in (baseline, candidate):
            print(f"{version}: fingerprint {self.fingerprint(PROMPTS[version])}")

        old, new = self.run(baseline), self.run(candidate)
        improved, regressed, critical_regressions = [], [], []

        print(f"\n{'case':<24} {baseline:<6} {candidate:<6}")
        for case, before, after in zip(CASES, old, new):
            mark = ""
            if after and not before:
                improved.append(case)
                mark = "improved"
            elif before and not after:
                regressed.append(case)
                mark = "REGRESSED" + (" (critical)" if case.critical else "")
                if case.critical:
                    critical_regressions.append(case)
            print(f"{str(case):<24} {'pass' if before else 'fail':<6} {'pass' if after else 'fail':<6} {mark}")

        print(f"\nScore: {baseline} {sum(old)}/{len(CASES)}, {candidate} {sum(new)}/{len(CASES)}")
        print(f"Improved: {len(improved)}, regressed: {len(regressed)}")

        if critical_regressions:
            print(f"Decision: keep {baseline}. {candidate} breaks a critical case: {critical_regressions[0]}.")
            return False
        if sum(new) < sum(old):
            print(f"Decision: keep {baseline}. {candidate} scores lower.")
            return False
        print(f"Decision: promote {candidate}.")
        return True


def main() -> None:
    """
    Compare a candidate prompt with the baseline.

    :return: None.
    """
    parser = argparse.ArgumentParser(description="Test a new prompt version before switching to it.")
    parser.add_argument("--baseline", choices=sorted(PROMPTS), default="v1")
    parser.add_argument("--candidate", choices=sorted(PROMPTS), default="v2")
    parser.add_argument("--model", help="Run the prompts on an installed Ollama model.")
    args = parser.parse_args()

    model: Model = OllamaModel(args.model) if args.model else FixtureModel()
    try:
        promoted = PromptComparison(model, Grader()).compare(args.baseline, args.candidate)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        parser.exit(1, f"Ollama HTTP {error.code}: {detail}\n")
    except (URLError, TimeoutError) as error:
        parser.exit(1, f"Could not run the model: {error}\n")

    # A non-zero exit lets a CI pipeline stop the release.
    raise SystemExit(0 if promoted else 1)


if __name__ == "__main__":
    # Example commands:
    #   uv run python 32_prompt_versioning.py --candidate v2
    #   uv run python 32_prompt_versioning.py --candidate v3
    #   uv run python 32_prompt_versioning.py --candidate v3 --model qwen
    main()
