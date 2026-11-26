"""
24_dynamic_delegation_and_handoffs.py

Let a planner split a task into parts, pick a specialist for each part,
pass work between specialists, and combine what they find.

Scenario:
    The same robot as examples 01-23: three moves from the lab, one battery
    unit, a battery that holds two. An operator asks: "Can the robot deliver
    the sample to the lab within 6 minutes?" No single specialist can answer.

Goal:
    Answer the question by delegating parts of it, without letting the
    planner invent specialists or skip the checks.

Difference from example 13:
    Example 13 always ran the same two specialists in a fixed order.
    Here the planner decides which specialists to use, and a specialist can
    hand its work to another one when the question is outside its job.

Flow:
    1. The planner reads the task and the list of specialists, and returns
       subtasks as JSON: which specialist, and what to ask.
    2. The coordinator rejects subtasks for specialists that do not exist.
    3. Each specialist either answers or hands off: "this is not my job,
       give it to X, and here is what I found so far".
    4. The coordinator follows handoffs (with a limit, so two specialists
       cannot pass work back and forth forever).
    5. The coordinator combines the findings into one answer.

New concepts:
    1. Delegation: a planner chooses who does what, instead of fixed code.
    2. A registry lists the specialists and what each one is for; the
       planner can only pick from it.
    3. A handoff transfers responsibility and carries context with it.
    4. A handoff limit stops endless passing.
    5. The coordinator, not the planner, combines results and decides.

Modes:
    1. --scripted        A fixture planner that also asks for a missing specialist.
    2. --model <name>    A local Ollama model plans the subtasks.

The specialists are plain code in both modes; only the planning changes.

Requirements:
    Python's standard library. Model mode also needs a running Ollama server.
"""

import argparse
import json
from dataclasses import dataclass, field
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BATTERY_CAPACITY = 2
MINUTES_PER_STEP = 1
MINUTES_PER_RECHARGE = 2
MAX_HANDOFFS = 2

TASK = "Can the robot deliver the sample to the lab within 6 minutes?"


@dataclass(frozen=True)
class RobotState:
    """
    What every specialist can read about the robot.
    """
    distance: int
    battery: int


@dataclass(frozen=True)
class Subtask:
    """
    One piece of work for one specialist.
    """
    specialist: str
    question: str


@dataclass
class Brief:
    """
    The context passed along with a subtask, growing as specialists add to it.
    """
    question: str
    notes: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Finding:
    """
    A specialist's answer.
    """
    specialist: str
    summary: str
    values: dict[str, int]


@dataclass(frozen=True)
class Handoff:
    """
    A specialist passing the work to another one, with what it found so far.
    """
    to: str
    reason: str
    notes: dict[str, int]


class Specialist(Protocol):
    """
    Anything that can work on a brief.
    """

    name: str
    purpose: str

    def work(self, brief: Brief, state: RobotState) -> Finding | Handoff:
        ...


class RouteSpecialist:
    """
    Knows how far the robot has to go.
    """

    name = "route"
    purpose = "How many steps remain to the destination."

    def work(self, brief: Brief, state: RobotState) -> Finding | Handoff:
        """
        :param brief: The question and notes so far.
        :param state: The robot's state.
        :return: The number of steps.
        """
        return Finding(self.name, f"{state.distance} step(s) to the lab.", {"steps": state.distance})


class BatterySpecialist:
    """
    Knows how many recharges a trip needs. Hands off questions about time.
    """

    name = "battery"
    purpose = "How many recharges a trip needs."

    def work(self, brief: Brief, state: RobotState) -> Finding | Handoff:
        """
        :param brief: The question and notes so far.
        :param state: The robot's state.
        :return: The recharges needed, or a handoff if asked about time.
        """
        missing = max(0, state.distance - state.battery)
        recharges = -(-missing // BATTERY_CAPACITY)  # Round up.

        if "minute" in brief.question.lower() or "time" in brief.question.lower():
            return Handoff(
                to="timing",
                reason="Time is not my job; I worked out the recharges for you.",
                notes={"recharges": recharges},
            )
        return Finding(self.name, f"{recharges} recharge(s) needed.", {"recharges": recharges})


class TimingSpecialist:
    """
    Turns steps and recharges into minutes. Needs both numbers.
    """

    name = "timing"
    purpose = "How many minutes a trip takes, given steps and recharges."

    def work(self, brief: Brief, state: RobotState) -> Finding | Handoff:
        """
        :param brief: The question and notes so far.
        :param state: The robot's state.
        :return: The trip time, or a handoff if recharges are unknown.
        """
        if "recharges" not in brief.notes:
            return Handoff(to="battery", reason="I need the number of recharges first.", notes={})

        steps = brief.notes.get("steps", state.distance)
        minutes = steps * MINUTES_PER_STEP + brief.notes["recharges"] * MINUTES_PER_RECHARGE
        return Finding(self.name, f"About {minutes} minute(s).", {"minutes": minutes})


class Planner(Protocol):
    """
    Anything that splits a task into subtasks.
    """

    def plan(self, task: str, registry: dict[str, Specialist]) -> str:
        ...


class ScriptedPlanner:
    """
    Return fixed subtasks, including one for a specialist that does not exist.
    """

    def plan(self, task: str, registry: dict[str, Specialist]) -> str:
        """
        :return: Subtasks as JSON text.
        """
        return json.dumps([
            {"specialist": "route", "question": "How far is the lab?"},
            {"specialist": "weather", "question": "Is it raining?"},
            {"specialist": "battery", "question": "How many minutes will charging and driving take?"},
        ])


class OllamaPlanner:
    """
    Ask a local Ollama model to split the task.
    """

    def __init__(self, model: str) -> None:
        """
        :param model: An installed Ollama model.
        """
        self.model = model

    def plan(self, task: str, registry: dict[str, Specialist]) -> str:
        """
        :param task:     The operator's question.
        :param registry: The specialists the model may choose.
        :return: The model's reply text.
        """
        listing = "\n".join(f"- {name}: {specialist.purpose}" for name, specialist in registry.items())
        prompt = (
            f"Task: {task}\nSpecialists:\n{listing}\n"
            "Split the task into subtasks for these specialists. Reply with only a JSON list like "
            '[{"specialist": "name", "question": "..."}].'
        )
        payload = {"model": self.model, "messages": [{"role": "user", "content": prompt}], "stream": False}
        request = Request(
            url="http://localhost:11434/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=120) as response:
            return (json.load(response).get("message") or {}).get("content", "")


class Coordinator:
    """
    Check the plan, run each subtask, follow handoffs, and combine the findings.
    """

    def __init__(self, planner: Planner, specialists: list[Specialist]) -> None:
        """
        :param planner:     Splits the task.
        :param specialists: Everyone who can be delegated to.
        """
        self.planner = planner
        self.registry: dict[str, Specialist] = {specialist.name: specialist for specialist in specialists}

    def subtasks(self, task: str) -> list[Subtask]:
        """
        Ask for a plan and keep only subtasks for registered specialists.

        :param task: The operator's question.
        :return: Valid subtasks.
        """
        reply = self.planner.plan(task, self.registry)
        try:
            items = json.loads(reply.strip().removeprefix("```json").removesuffix("```"))
        except json.JSONDecodeError:
            raise ValueError(f"The plan is not JSON: {reply!r}")
        if not isinstance(items, list):
            raise ValueError("The plan must be a JSON list.")

        valid = []
        for item in items:
            name = item.get("specialist") if isinstance(item, dict) else None
            if name not in self.registry:
                print(f"  rejected: unknown specialist {name!r}")
                continue
            valid.append(Subtask(name, str(item.get("question", ""))))
            print(f"  {name} <- {valid[-1].question!r}")
        return valid

    def delegate(self, subtask: Subtask, state: RobotState, notes: dict[str, int]) -> Finding | None:
        """
        Run one subtask, following handoffs up to MAX_HANDOFFS times.

        :param subtask: Who to ask, and what.
        :param state:   The robot's state.
        :param notes:   Values found by earlier subtasks, shared as context.
        :return: The final finding, or None if the handoff limit was reached.
        """
        brief = Brief(question=subtask.question, notes=dict(notes))
        current = subtask.specialist

        for _ in range(MAX_HANDOFFS + 1):
            result = self.registry[current].work(brief, state)
            if isinstance(result, Finding):
                print(f"  {current}: {result.summary}")
                return result

            if result.to not in self.registry:
                print(f"  {current}: tried to hand off to unknown {result.to!r}; stopped.")
                return None
            print(f"  {current} -> {result.to}: {result.reason}")
            brief.notes.update(result.notes)
            current = result.to

        print(f"  Stopped after {MAX_HANDOFFS} handoffs.")
        return None

    def answer(self, task: str, state: RobotState, limit_minutes: int) -> str:
        """
        Run the whole delegation and decide.

        :param task:          The operator's question.
        :param state:         The robot's state.
        :param limit_minutes: The deadline in the question.
        :return: The combined answer.
        """
        notes: dict[str, int] = {}
        print("\nPlan:")
        subtasks = self.subtasks(task)
        print("\nWork:")
        for subtask in subtasks:
            finding = self.delegate(subtask, state, notes)
            if finding is not None:
                notes.update(finding.values)

        print(f"\nCombined findings: {notes}")
        if "minutes" not in notes:
            return "Cannot answer: no specialist produced a trip time."
        verdict = "Yes" if notes["minutes"] <= limit_minutes else "No"
        return f"{verdict}: the trip takes about {notes['minutes']} minute(s); the limit is {limit_minutes}."


def main() -> None:
    """
    Answer the delivery question with a scripted or a model planner.

    :return: None.
    """
    parser = argparse.ArgumentParser(description="Delegate a task to specialists, with handoffs.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scripted", action="store_true", help="Use the fixture planner.")
    mode.add_argument("--model", help="An installed Ollama model plans the subtasks.")
    parser.add_argument("--limit", type=int, default=6, help="Deadline in minutes.")
    args = parser.parse_args()

    planner: Planner = OllamaPlanner(args.model) if args.model else ScriptedPlanner()
    coordinator = Coordinator(planner, [RouteSpecialist(), BatterySpecialist(), TimingSpecialist()])
    task = f"Can the robot deliver the sample to the lab within {args.limit} minutes?"
    print(f"Task: {task}")

    try:
        print("\nAnswer:", coordinator.answer(task, RobotState(distance=3, battery=1), args.limit))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        parser.exit(1, f"Ollama HTTP {error.code}: {detail}\n")
    except (URLError, TimeoutError, ValueError) as error:
        parser.exit(1, f"Could not finish the task: {error}\n")


if __name__ == "__main__":
    # Example commands:
    #   uv run python 24_dynamic_delegation_and_handoffs.py --scripted
    #   uv run python 24_dynamic_delegation_and_handoffs.py --scripted --limit 4
    #   uv run python 24_dynamic_delegation_and_handoffs.py --model qwen
    main()
