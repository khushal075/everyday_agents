"""
19_context_budget_and_summarization.py

Keep a long trip's conversation inside the model's context budget.

Scenario:
    The same robot as examples 01-18, on a longer trip: nine moves from the
    destination, one battery unit, a battery that holds two. Every action adds
    a tool result to the conversation, so the history keeps growing.

Goal:
    Send the model what it needs for the next decision without exceeding
    a fixed token budget.

Difference from example 09:
    Example 09 remembered one topic. Here the whole history is kept until it
    no longer fits; then older events are replaced by a short summary.

Flow:
    1. Run the trip and record every action as an event.
    2. Before each decision, build the context:
        - Pinned: the system prompt, the goal, and the current state read
          from the environment. These are always sent.
        - Recent: the newest events, as many as fit in the budget.
        - Summary: older events, compressed into a few lines.
    3. Print how large the full history is and what was actually sent.

New concepts:
    1. Models have a context limit, and every token sent costs time and money.
    2. Tokens are estimated here as characters / 4; real tokenizers differ.
    3. Pinned facts are never summarized: the current state comes from the
       environment, so a lossy or wrong summary cannot corrupt it.
    4. Recent events are kept word for word; older ones are summarized.
    5. If the pinned facts and summary alone do not fit, the run stops
       instead of silently dropping them.

Modes:
    1. --scripted              A rule-based summarizer that counts events.
    2. --model <name>          A local Ollama model writes the summary.

The robot's decisions use a fixed rule in both modes, so only the
context building changes between them.

Requirements:
    Python's standard library. Model mode also needs a running Ollama server.
"""

import argparse
import json
import math
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BATTERY_CAPACITY = 2

SYSTEM_PROMPT = (
    "You control a robot through move and recharge tools. "
    "Use the current state to choose the next action."
)


@dataclass(frozen=True)
class Observation:
    """
    The robot's remaining distance and battery.
    """
    distance: int
    battery: int


@dataclass(frozen=True)
class Event:
    """
    One recorded action and the state it left behind.
    """
    step: int
    action: str
    amount: int
    success: bool
    message: str
    after: Observation

    def as_text(self) -> str:
        """
        Render the event the way it would appear in the conversation.

        :return: One line describing the event.
        """
        outcome = "ok" if self.success else "rejected"
        return (
            f"Step {self.step}: {self.action} {self.amount} -> {outcome}: {self.message} "
            f"(distance {self.after.distance}, battery {self.after.battery})"
        )


@dataclass(frozen=True)
class Context:
    """
    The messages chosen for one decision, and how large they are.
    """
    messages: list[dict]
    tokens: int
    summarized_events: int
    recent_events: int


class Summarizer(Protocol):
    """
    Anything that compresses a list of events into short text.
    """

    def summarize(self, events: list[Event]) -> str:
        ...


class Environment:
    """
    Simulate the robot, as in examples 03 and 16.
    """

    def __init__(self, distance: int, battery: int) -> None:
        """
        Set the starting state.

        :param distance: Steps to the destination.
        :param battery:  Starting battery units.
        """
        self.distance = distance
        self.battery = battery

    def observe(self) -> Observation:
        """
        Return the current state.

        :return: A new Observation.
        """
        return Observation(distance=self.distance, battery=self.battery)

    def move(self, steps: int) -> tuple[bool, str]:
        """
        Move if the distance and battery allow it.

        :param steps: Requested steps.
        :return: Whether it happened, and a message.
        """
        if steps > self.distance:
            return False, "Cannot move beyond the destination."
        if steps > self.battery:
            return False, f"Not enough battery: {self.battery} unit(s) left."
        self.distance -= steps
        self.battery -= steps
        return True, f"Moved {steps} step(s)."

    def recharge(self, units: int) -> tuple[bool, str]:
        """
        Add battery units without exceeding capacity.

        :param units: Requested units.
        :return: Whether it happened, and a message.
        """
        if self.battery + units > BATTERY_CAPACITY:
            return False, f"Battery capacity ({BATTERY_CAPACITY}) would be exceeded."
        self.battery += units
        return True, f"Recharged {units} unit(s)."


class TripPolicy:
    """
    A fixed rule that picks the next action, including one deliberate mistake.

    The mistake (trying to move 2 with 1 unit on step 1) adds a rejected
    event, so the summary has something to report.
    """

    def choose(self, step: int, state: Observation) -> tuple[str, int]:
        """
        Pick the next action from the current state.

        :param step:  The step number, starting at 1.
        :param state: The current state.
        :return: The action name and its amount.
        """
        if step == 1:
            return "move", 2
        if state.battery == 0:
            return "recharge", BATTERY_CAPACITY
        return "move", min(state.battery, state.distance)


class TokenCounter:
    """
    Estimate how many tokens a text uses.
    """

    def count(self, text: str) -> int:
        """
        Use the common rule of thumb of four characters per token.

        :param text: Any text.
        :return: The estimated token count.
        """
        return math.ceil(len(text) / 4)


class RuleSummarizer:
    """
    Summarize events by counting them; no model is involved.
    """

    def summarize(self, events: list[Event]) -> str:
        """
        Report steps covered, distance moved, recharges, and rejections.

        :param events: Older events to compress.
        :return: A short summary.
        """
        moved = sum(event.amount for event in events if event.action == "move" and event.success)
        recharges = sum(1 for event in events if event.action == "recharge" and event.success)
        rejected = [event for event in events if not event.success]

        summary = (
            f"Steps {events[0].step}-{events[-1].step}: moved {moved} step(s), "
            f"recharged {recharges} time(s), {len(rejected)} rejected action(s)."
        )
        for event in rejected:
            summary += f" Step {event.step} rejected: {event.message}"
        return summary


class OllamaSummarizer:
    """
    Ask a local Ollama model to summarize older events.
    """

    def __init__(self, model: str) -> None:
        """
        Store the installed model name.

        :param model: An installed Ollama model.
        """
        self.model = model

    def summarize(self, events: list[Event]) -> str:
        """
        Send the events and ask for a two-sentence summary.

        :param events: Older events to compress.
        :return: The model's summary.
        """
        prompt = (
            "Summarize these robot trip events in at most two sentences. "
            "Mention any rejected actions and why.\n\n"
            + "\n".join(event.as_text() for event in events)
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        request = Request(
            url="http://localhost:11434/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=120) as response:
            message = json.load(response).get("message")

        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ValueError("The response did not contain message text.")
        return message["content"].strip()


class ContextBuilder:
    """
    Fit pinned facts, a summary, and recent events into a token budget.
    """

    def __init__(self, budget: int, counter: TokenCounter, summarizer: Summarizer) -> None:
        """
        Store the budget and the helpers.

        :param budget:     Maximum estimated tokens per request.
        :param counter:    Estimates tokens.
        :param summarizer: Compresses older events.
        """
        self.budget = budget
        self.counter = counter
        self.summarizer = summarizer
        self.summary_cache: dict[int, str] = {}

    def full_size(self, goal: str, state: Observation, events: list[Event]) -> int:
        """
        Estimate the tokens needed to send the whole history with no summary.

        :param goal:   The trip's goal.
        :param state:  The current state.
        :param events: Every event so far.
        :return: The estimated token count.
        """
        texts = [SYSTEM_PROMPT, goal, f"Current state: distance {state.distance}, battery {state.battery}."]
        texts.extend(event.as_text() for event in events)
        return sum(self.counter.count(text) for text in texts)

    def build(self, goal: str, state: Observation, events: list[Event]) -> Context:
        """
        Choose what to send for the next decision.

        Start with every event word for word. While the context is over
        budget, move the oldest event into the summary.

        :param goal:   The trip's goal.
        :param state:  The current state, read from the environment.
        :param events: Every event so far, oldest first.
        :return: The messages to send and their size.
        """
        older: list[Event] = []
        recent = list(events)

        while True:
            messages = self._messages(goal, state, older, recent)
            tokens = sum(self.counter.count(message["content"]) for message in messages)
            if tokens <= self.budget:
                return Context(messages, tokens, summarized_events=len(older), recent_events=len(recent))
            if not recent:
                # Nothing left to summarize: the pinned facts and summary alone are too big.
                raise ValueError(f"The context needs {tokens} tokens even with every event summarized.")
            older.append(recent.pop(0))

    def _messages(self, goal: str, state: Observation, older: list[Event], recent: list[Event]) -> list[dict]:
        """
        Assemble the messages: pinned facts, the summary, recent events, the current state.

        :param goal:   The trip's goal.
        :param state:  The current state.
        :param older:  Events to summarize.
        :param recent: Events to send word for word.
        :return: The messages, in order.
        """
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": goal},
        ]
        if older:
            messages.append({"role": "user", "content": "Earlier: " + self._summary(older)})
        messages.extend({"role": "tool", "content": event.as_text()} for event in recent)
        # The current state is pinned and goes last, closest to the decision.
        messages.append({"role": "user", "content": f"Current state: distance {state.distance}, battery {state.battery}."})
        return messages

    def _summary(self, older: list[Event]) -> str:
        """
        Summarize older events, reusing the summary when the same events repeat.

        :param older: Events to compress, oldest first.
        :return: The summary text.
        """
        last_step = older[-1].step
        if last_step not in self.summary_cache:
            self.summary_cache[last_step] = self.summarizer.summarize(older)
        return self.summary_cache[last_step]


class Agent:
    """
    Run the trip and build a budgeted context before every decision.
    """

    def __init__(
            self,
            environment: Environment,
            policy: TripPolicy,
            builder: ContextBuilder,
    ) -> None:
        """
        Connect the robot, the decision rule, and the context builder.

        :param environment: The simulated robot.
        :param policy:      Picks each action.
        :param builder:     Fits the context into the budget.
        """
        self.environment = environment
        self.policy = policy
        self.builder = builder

    def run(self, max_steps: int = 20) -> list[Event]:
        """
        Drive to the destination, printing context sizes along the way.

        :param max_steps: Stop after this many actions.
        :return: Every event recorded.
        """
        start = self.environment.observe()
        goal = f"Reach the destination {start.distance} steps away. The battery holds {BATTERY_CAPACITY} units."
        events: list[Event] = []
        context: Context | None = None

        for step in range(1, max_steps + 1):
            state = self.environment.observe()
            if state.distance == 0:
                break

            context = self.builder.build(goal, state, events)
            full_tokens = self.builder.full_size(goal, state, events)
            print(
                f"Step {step:>2}: full history ~{full_tokens:>3} tokens, sent ~{context.tokens:>3} "
                f"({context.summarized_events} summarized, {context.recent_events} recent)"
            )

            action, amount = self.policy.choose(step, state)
            if action == "move":
                success, message = self.environment.move(amount)
            else:
                success, message = self.environment.recharge(amount)
            events.append(Event(step, action, amount, success, message, self.environment.observe()))

        if context is not None:
            print("\nLast context sent:")
            for message in context.messages:
                print(f"  [{message['role']}] {message['content']}")
        return events


def main() -> None:
    """
    Run a long trip with a summarizer that counts or one that uses a model.

    :return: None.
    """
    parser = argparse.ArgumentParser(description="Keep a long trip inside a token budget.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scripted", action="store_true", help="Use the rule-based summarizer.")
    mode.add_argument("--model", help="An installed Ollama model writes the summaries.")
    parser.add_argument("--budget", type=int, default=150, help="Maximum estimated tokens per request.")
    parser.add_argument("--distance", type=int, default=9)
    args = parser.parse_args()

    if args.budget < 1 or args.distance < 1:
        parser.error("--budget and --distance must be at least 1.")

    counter = TokenCounter()
    summarizer: Summarizer = OllamaSummarizer(args.model) if args.model else RuleSummarizer()
    agent = Agent(
        environment=Environment(distance=args.distance, battery=1),
        policy=TripPolicy(),
        builder=ContextBuilder(budget=args.budget, counter=counter, summarizer=summarizer),
    )

    try:
        events = agent.run()
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        parser.exit(1, f"Ollama HTTP {error.code}: {detail}\n")
    except (URLError, TimeoutError, ValueError) as error:
        parser.exit(1, f"Could not build the context: {error}\n")

    print(f"\nTrip finished after {len(events)} actions.")


if __name__ == "__main__":
    # Example commands:
    #   uv run python 19_context_budget_and_summarization.py --scripted
    #   uv run python 19_context_budget_and_summarization.py --scripted --budget 100
    #   uv run python 19_context_budget_and_summarization.py --scripted --budget 40
    #   uv run python 19_context_budget_and_summarization.py --model qwen
    main()
