"""
17_structured_output_and_repair.py

Ask the model for robot's whole trip plan as JSON, and repair until it works.

Goal:
    Reach the destination three moves away with a battery that can holds two units MAX.

Difference from example 16
    - Example 16 one tool call at a time while the robot moves.
    - Here the model returns the complete plan first, and the plan is checked before the robot
      takes a single step.

Flow:
    1. Send the robot's state and the expected JSON shape to the model.
    2. Parse the reply as JSON.
    3. Validate its shape; Fields, Allowed actions and integer amounts.
    4. Simulate the plan:
        - Enough battery for every move
        - No overcharge
        - Robot ends exactly at destination.
    5. If anything wrong, send the errors back and ask for the corrected plan.
    6. Repeat until the plan is valid or the repair limit is reached.

New Concepts:
    1. Parsing is separate from validation:
        - Valid JSON can still be the wrong plan.
    2. Shape errors are reported together.
        - So that one repair can fix several problems.
    3. Shape rules (types, allowed values) differ from business rules
       which here are checked by simulating the plan.
    4. Constrained decoding (--constrained) makes the model follow the JSON schema.
    5. It enforces shape only; whether the plan works still needs code.
    6. A repair limit stops a model that never produces a valid reply.
    7. Repeating the same rejected reply ends the run early (no_progress).

Modes:
    1. --scripted repairs     Fixture replies that fail three ways, then succeed.
    2. --scripted gives_up    Fixture replies that repeat the same short plan (ends in no_progress).
    3. --model <name>         A local Ollama model.

Scripted mode does not run the model. It replays fixed replies to show
how parsing, validation and repair handle them.

Requirements:
    1. Python's standard library.
    2. Model mode needs a running Ollama server.
"""

import argparse
import json
from dataclasses import dataclass
from typing import Literal, Protocol, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

RunStatus = Literal["valid", "invalid_after_repairs", "no_progress"]

Scenario = Literal["repairs", "gives_up"]
Action = Literal["move", "recharge"]

ACTIONS = ("move", "recharge")
BATTERY_CAPACITY = 2
MAX_ACTIONS = 6

# The shape a plan must have.
# It is shown to the model in the prompt and sent as a constraint when --constraint is used.

ACTION_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS)},
            "amount": {"type": "integer"},
        },
        "required": ["action", "amount"],
        "additionalProperties": False,
    }
}


PLAN_SCHEMA = {
    "type": "object",
    "properties": {"actions": ACTION_SCHEMA, "reason": {"type": "string"}},
    "required": ["actions", "reason"],
    "additionalProperties": False
}


SYSTEM_PROMPT = " ".join([
    "You plan trips for the robot.",
    "move uses one battery battery unit per step. recharge adds battery units.",
    f"The battery holds at most {BATTERY_CAPACITY} units.",
    f"A plan has at most {MAX_ACTIONS} actions and must end exactly at the destination.",
    "Reply with only JSON object that matches this schema:",json.dumps(PLAN_SCHEMA),
])


@dataclass(frozen=True)
class Observation:
    """
        The robot remaining distance and battery.
    """
    distance: int
    battery: int

@dataclass(frozen=True)
class PlannedAction:
    action: Action
    amount: int


@dataclass(frozen=True)
class TripPlan:
    """
        A plan whose shape and effect have both been checked.
    """
    actions: tuple[PlannedAction, ...]
    reason: str

@dataclass(frozen=True)
class ShapeResult:
    """
        The outcome of the shape check: the valid parts found, and every error.
    """
    actions: tuple[PlannedAction, ...] = ()
    reason: str = ""
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class CheckResult:
    """
        The outcome of checking one model reply.

        Exactly one of the plan or errors is set.
    """
    plan: Optional[TripPlan]
    errors: tuple[str, ...] = ()


class ChatModel(Protocol):
    """
        Anything that turns a conversation into reply text.
    """
    def chat(self, messages: list[dict]) -> str:
        ...


class ReplyParser:
    """
        Turn the model's reply text into a JSON value.
    """
    def parse(self, text: str) -> tuple[Optional[object], Optional[str]]:
        """
            Parse the reply as JSON, allowing only a surrounding Markdown code fence.

            Text before or after the JSON is not searched; the reply is rejected instead.

        :param text:    The model's raw reply.

        :return:        The parsed value and None, or None and the parsed error.
        """
        cleaned = text.strip()
        if cleaned.startswith("```") and cleaned.endswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(lines[1:-1]).strip()
            print("  NOTE: removed a Markdown code fence.")

        try:
            return json.loads(cleaned), None
        except json.JSONDecodeError as error:
            return None, f"The reply must be only a JSON object. JSON error: {error.msg}."


class ShapeValidator:
    """
        Check a parsed plan's fields and types against PLAN_SCHEMA.
    """

    def validate(self, value: object) -> ShapeResult:
        """
            Collect every shape error, so one repair can fix several problems.

            Checks:
                - The value is an object with no unknown fields.
                - Reason is non-empty string.
                - Actions is a non-empty list of at most MAX_ACTIONS items.
                - Each action is 'move' or 'recharge' with a positive integer amount.

        :param value:       The parsed reply.

        :return:            The valid actions and reason found, and every shape error.
        """
        if not isinstance(value, dict):
            return ShapeResult(errors=("The reply must be a JSON object.",))

        errors: list[str] = []
        unknown = sorted(set(value) - set(PLAN_SCHEMA['properties']))
        if unknown:
            errors.append(f"Unknown field(s): {', '.join(unknown)}")
        reason = value.get("reason")

        if not isinstance(reason, str) or not reason.strip():
            errors.append("Reason must be non-empty string.")
            reason = ""

        raw_actions = value.get("actions")
        if not isinstance(raw_actions, list) or not raw_actions:
            errors.append("actions must be non-empty list.")
            return ShapeResult(reason=reason.strip(), errors=tuple(errors))

        if len(raw_actions) > MAX_ACTIONS:
            errors.append(f"Actions must be at most {MAX_ACTIONS} actions; got {len(raw_actions)}.")

        actions: list[PlannedAction] = []
        for number, item in enumerate(raw_actions, start=1):
            action = self._validate_action(number, item, errors)
            if action is not None:
                actions.append(action)

        return ShapeResult(
            actions=tuple(actions),
            reason=reason.strip(),
            errors=tuple(errors)
        )

    def _validate_action(self, number: int, item: object, errors: list[str]) -> Optional[PlannedAction]:
        """
        Check one action, adding any problems to errors.


        :param number:  The action's position in the plan, starting at 1.
        :param item:    The action as the mode wrote it.
        :param errors:  The list collecting every shape error.

        :return:        The validated action, or None if it has errors.
        """
        if not isinstance(item, dict) or set(item) != {"action", "amount"}:
            errors.append(f"Action {number}: expected exactly 'action' and 'amount'.")
            return None

        action, amount = item["action"], item["amount"]
        valid = True
        if action not in ACTIONS:
            errors.append(f"Action {number}: expected one of {', '.join(ACTIONS)}, got {action!r}.")
            valid = False

        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            errors.append(f"Action {number}: amount must be a positive integer; got {amount!r}.")
            valid = False

        return PlannedAction(action=action, amount=amount) if valid else None

class PlanSimulator:
    """
    Check the business rules by running the plan on a copy of the robot's state.
    """
    def simulate(self, actions: tuple[PlannedAction, ...], start: Observation) -> Optional[str]:
        """
            Run the plan without moving the robot.

            Each action depends on the state left by previous one, so the simulation
            stops at the first action they cannot run.


        :param actions:     Action that passed the shape check.
        :param start:       The robot's current state.

        :return:            The first business-rule error, or None if the plan works.
        """
        distance, battery = start.distance, start.battery
        for number, step in enumerate(actions, start=1):
            if step.action == "move":
                if step.amount > distance:
                    return f"Action {number}: move {step.amount} goes past the destination ({distance} step(s) left)."
                if step.amount > battery:
                    return f"Action {number}: move {step.amount} needs {step.amount} battery unit(s); only {battery} left."
                distance -= step.amount
                battery -= step.amount
            else:
                if battery + step.amount > BATTERY_CAPACITY:
                    return f"Action {number}: recharge {step.amount} exceeds capacity ({battery} of {BATTERY_CAPACITY} units)."
                battery += step.amount

        if distance != 0:
            return f"The plan ends {distance} step(s) short of the destination."
        return None

class OllamaChatModel:
    """
        Ask a local Ollama model for a trip plan.
    """
    def __init__(self, model: str, constrained: bool = False) -> None:
        """
            Store the model name and whether to constraint the output shape.

        :param model:           An installed Ollama model.
        :param constrained:     Send PLAN_SCHEMA as the required output format.
        """
        self.model = model
        self.constrained = constrained

    def chat(self, messages: list[dict]) -> str:
        """
            Send the conversation and return the reply text.

        :param messages:    The conversation so for.
        :return:            The model's reply text.
        """
        payload: dict = {"model": self.model, "messages": messages, "stream": False}
        if self.constrained:
            payload["format"] = PLAN_SCHEMA

        request = Request(
            url="http://localhost:11434/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        with urlopen(request, timeout=120) as response:
            message = json.load(response).get("message")

        if not isinstance(message, dict) or not isinstance(message.get('content'), str):
            raise ValueError("The response did not contain message text")

        return message["content"]


class ScriptedChatModel:
    """
        Replay fixed replies instead of running the model.

        The replies ignore the conversation and assume the default start
        (distance 3, battery 1). They show how parsing, validation and repair
        handle common mistakes.
    """
    SCRIPTS: dict[Scenario, list[str]] = {
        "repairs": [
            # Extra text around the JSON: parsing fails.
            'Here is the plan:\n```json\n{"actions": [{"action": "move", "amount": 3}]}\n```',
            # Valid JSON, wrong shape: several errors reported together.
            '{"actions": [{"action": "Move", "amount": "1"}, {"action": "teleport", "amount": 2}]}',
            # Correct shape, but the plan fails in simulation.
            '{"actions": [{"action": "move", "amount": 3}], "reason": "Go straight there."}',
            # Valid, inside a code fence that the parser allows.
            '```json\n{"actions": [{"action": "move", "amount": 1}, {"action": "recharge", "amount": 2},'
            ' {"action": "move", "amount": 2}], "reason": "Use the one unit, recharge, then finish."}\n```',
        ],
        "gives_up": [
            '{"actions": [{"action": "move", "amount": 1}], "reason": "Move while battery lasts."}'
        ] * 4,
    }

    def __init__(self, scenario: Scenario) -> None:
        """
            Select the fixture replies to reply.

        :param scenario:    Which scripted behavior to show.
        """
        self.replies = list(self.SCRIPTS[scenario])

    def chat(self, messages: list[dict]) -> str:
        """
            Return the next fixture replies.

        :param messages:    Ignored by the fixture.

        :return:            A scripted reply.
        """
        if not self.replies:
            return "Script finished."

        return self.replies.pop(0)

class Agent:
    """
        Ask for a plan, check it, and request repairs until it is valid.
    """

    def __init__(
        self,
        model: ChatModel,
        parser: ReplyParser,
        validator: ShapeValidator,
        simulator: PlanSimulator,
    ) -> None:
        """
            Connect the model to the three checking components.

        :param model:           Produces reply text from conversation.
        :param parser:          Turns reply text into JSON.
        :param validator:       Checks the plan's shape.
        :param simulator:       Checks the plan's effect.
        """
        self.model = model
        self.parser = parser
        self.validator = validator
        self.simulator = simulator

    def check(self, reply: str, start: Observation) -> CheckResult:
        """
            Parse, then check the shape, then simulate; Stop at first stage that fails.

        :param reply:       The model's raw reply.
        :param start:       The robot's current state.

        :return:            A TripPlan, or the errors from the failing stage.
        """
        value, parse_error = self.parser.parse(reply)

        if parse_error is not None:
            return CheckResult(plan=None, errors=(parse_error, ))

        shape = self.validator.validate(value)

        if shape.errors:
            return CheckResult(plan=None, errors=shape.errors)

        rule_error = self.simulator.simulate(shape.actions, start)
        if rule_error is not None:
            return CheckResult(plan=None, errors=(rule_error, ))

        return CheckResult(
            plan= TripPlan(actions=shape.actions, reason=shape.reason),
        )

    def run(self, start: Observation, max_repairs: int = 3) -> tuple[RunStatus, Optional[TripPlan]]:
        """
            Return a valid plan, or stop after max_repairs failed repairs.


        :param start:               The robot's current state.
        :param max_repairs:         Correction requests allowed after the first reply.

        :return:                    The status and the plan, if one was accepted.
        """
        if not isinstance(max_repairs, int) or isinstance(max_repairs, bool) or max_repairs < 0:
            raise ValueError("max_repairs must be a non-negative integer.")

        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"Plan the trip. Distance: {start.distance}. "
                f"Battery: {start.battery} of {BATTERY_CAPACITY} units."
            )}
        ]

        previous_reply: str | None = None
        for attempt in range(1, max_repairs + 2):
            reply = self.model.chat(messages)
            print(f"Attempt {attempt}: {reply!r}")

            if previous_reply is not None and reply.strip() == previous_reply.strip():
                print("   Same reply as the last attempt; stopping.")
                return "no_progress", None
            previous_reply = reply

            result = self.check(reply, start)
            if result.plan is not None:
                print("    Accepted    ")
                return "valid", result.plan

            for error in result.errors:
                print(f"    Error: {error!r}")

            # The rejected reply and every error become the model's next input.
            messages.append({"role": "assistant", "content": reply})
            messages.append({
                "role": "user",
                "content": (
                    "Your plan was not accepted:\n"
                    + "\n".join(f"- {error}" for error in result.errors)
                    + "\nReturn only the corrected JSON object."
                )
            })

        return "invalid_after_repairs", None

def main():
    """
        Plan one trip using a local model or a scripted fixture.

    :return:        None.
    """
    parser = argparse.ArgumentParser(description="Get a validated trip plan as JSON.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--model", help="An installed Ollama model.")
    mode.add_argument("--scripted", choices=["repairs", "gives_up"],
                      help="Replay fixture replies instead of calling a model.")
    parser.add_argument("--constrained", action="store_true",
                        help="Ask Ollama to follow PLAN_SCHEMA (model mode only).")
    parser.add_argument("--distance", type=int, default=3)
    parser.add_argument("--battery", type=int, default=1, choices=range(0, BATTERY_CAPACITY + 1))
    parser.add_argument("--max-repairs", type=int, default=3)
    args = parser.parse_args()

    if args.distance < 1:
        parser.error("--distance must be at least 1.")

    model: ChatModel = (
        OllamaChatModel(args.model, args.constrained) if args.model
        else ScriptedChatModel(args.scripted)
    )
    start = Observation(distance=args.distance, battery=args.battery)

    try:
        agent = Agent(
            model=model,
            parser=ReplyParser(),
            validator=ShapeValidator(),
            simulator=PlanSimulator(),
        )
        status, plan = agent.run(start, max_repairs=args.max_repairs)

    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        parser.exit(1, f"Ollama HTTP {error.code}: {detail}\n")
    except (URLError, TimeoutError, ValueError) as error:
        parser.exit(1, f"Could not run the model: {error}\n")

    print("Final status:", status)
    if plan is not None:
        for step in plan.actions:
            print(f"  {step.action} {step.amount}")
        print("Reason:", plan.reason)


if __name__ == "__main__":
    # Example commands:
    #   uv run python 17_structured_output_and_repair.py --scripted repairs
    #   uv run python 17_structured_output_and_repair.py --scripted gives_up
    #   uv run python 17_structured_output_and_repair.py --model qwen
    #   uv run python 17_structured_output_and_repair.py --model qwen --constrained
    #   uv run python 17_structured_output_and_repair.py --model qwen --distance 7
    main()
