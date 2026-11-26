"""
27_streaming_and_interruption.py

Show progress while the robot works, accept a correction halfway through,
and stop safely when canceled.

Scenario:
    The same robot as examples 01-26: three moves from the destination,
    one battery unit, a battery that holds two. Each action takes a moment,
    so the operator watches progress and may change their mind.

Goal:
    Keep the operator informed as work happens, apply their corrections,
    and never leave the robot halfway through an action.

Difference from example 16:
    Example 16 printed results after each step and could not be changed
    once started. Here progress streams out as it happens, and messages
    from the operator are read while the trip is running.

Flow:
    1. A narrator streams a short description of the plan, word by word.
    2. The trip runs one action at a time and reports progress after each.
    3. Between actions (the safe points), the agent reads its inbox:
        - A correction changes the goal; the next action uses the new goal.
        - A cancel stops the trip at the safe point and reports where it is.
    4. Pressing Ctrl+C asks for a cancel: the current action finishes first.

New concepts:
    1. Streaming: send output as it is produced instead of all at the end.
    2. Safe points: messages are applied only between actions, never during one.
    3. A correction changes the plan without restarting the task.
    4. Cancellation is a request; the agent finishes the current action,
       then stops and reports a known state.
    5. Ctrl+C is caught and turned into the same safe cancel.

Modes:
    1. --scripted          The inbox receives a correction, then a cancel.
    2. --interactive       Enter further N to correct the destination; cancel or Ctrl+C stops.
    3. --model <name>      Like --interactive, but a local Ollama model
                           streams the plan description.

Requirements:
    Python's standard library. Model mode also needs a running Ollama server.
"""

import argparse
import json
import signal
import queue
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BATTERY_CAPACITY = 2
SECONDS_PER_ACTION = 0.6

PLAN_PROMPT = (
    "In two short sentences, describe how a robot 3 steps from its goal with 1 battery unit "
    f"(capacity {BATTERY_CAPACITY}, one unit per step) should reach it."
)


@dataclass(frozen=True)
class Message:
    """
    Something the operator sent while the trip was running.
    """
    kind: str  # "correction" or "cancel"
    extra_steps: int = 0


class Narrator(Protocol):
    """
    Anything that streams text piece by piece.
    """

    def stream(self) -> Iterator[str]:
        ...


class ScriptedNarrator:
    """
    Stream a fixed description one word at a time.
    """

    TEXT = "Move one step, recharge to full, then move the last two steps."

    def stream(self) -> Iterator[str]:
        """
        :return: Words, with a short pause between them.
        """
        for word in self.TEXT.split():
            time.sleep(0.05)
            yield word + " "


class OllamaNarrator:
    """
    Stream a description from a local Ollama model as it is generated.
    """

    def __init__(self, model: str) -> None:
        """
        :param model: An installed Ollama model.
        """
        self.model = model

    def stream(self) -> Iterator[str]:
        """
        Read Ollama's streamed reply: one JSON object per line, each with a piece of text.

        :return: Pieces of text as they arrive.
        """
        payload = {"model": self.model, "messages": [{"role": "user", "content": PLAN_PROMPT}], "stream": True}
        request = Request(
            url="http://localhost:11434/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=120) as response:
            for line in response:
                chunk = json.loads(line)
                yield (chunk.get("message") or {}).get("content", "")
                if chunk.get("done"):
                    break


class Inbox:
    """
    Hold operator messages until the agent reaches a safe point.
    """

    def __init__(self, scheduled: dict[int, Message] | None = None) -> None:
        """
        :param scheduled: Messages that arrive after a given step (for scripted runs).
        """
        self.scheduled = scheduled or {}
        self.cancel_requested = False
        self.pending: queue.SimpleQueue[Message] = queue.SimpleQueue()

    def request_cancel(self, signal_number: int = 0, frame: object = None) -> None:
        """
        Record a cancel request. Used as the Ctrl+C handler, so it must not stop anything itself.

        :return: None.
        """
        if not self.cancel_requested:
            print("\n  (Cancel requested; finishing the current action first.)")
        self.cancel_requested = True

    def read_commands(self) -> None:
        """Queue terminal corrections and cancellation without interrupting an action.

        Enter `further N` to extend the remaining trip, or `cancel` to stop.
        EOF ends input while allowing the trip to continue.
        """
        while True:
            try:
                command = input().strip().lower()
            except EOFError:
                return
            if command == "cancel":
                self.pending.put(Message("cancel"))
                return
            parts = command.split()
            if len(parts) == 2 and parts[0] == "further":
                try:
                    amount = int(parts[1])
                except ValueError:
                    amount = 0
                if amount > 0:
                    self.pending.put(Message("correction", extra_steps=amount))
                    continue
            print("Enter further N (a positive integer), or cancel.", flush=True)

    def collect(self, after_step: int) -> list[Message]:
        """
        Return every message waiting at this safe point.

        :param after_step: The step that just finished.
        :return: Waiting messages, oldest first.
        """
        messages = []
        if after_step in self.scheduled:
            messages.append(self.scheduled.pop(after_step))
        while True:
            try:
                messages.append(self.pending.get_nowait())
            except queue.Empty:
                break
        if self.cancel_requested:
            messages.append(Message("cancel"))
        return messages


class Trip:
    """
    Run the trip one action at a time, yielding progress after each action.
    """

    def __init__(self, distance: int, battery: int) -> None:
        """
        :param distance: Steps to the destination.
        :param battery:  Starting battery units.
        """
        self.distance = distance
        self.battery = battery

    def actions(self) -> Iterator[str]:
        """
        Do the next action, then yield a progress line. Stops when the robot arrives.

        Each action finishes completely before the line is yielded, so the
        caller only ever sees the robot between actions.

        :return: Progress lines.
        """
        while self.distance > 0:
            time.sleep(SECONDS_PER_ACTION)  # The action takes time; Ctrl+C here waits for it.
            if self.battery == 0:
                self.battery = BATTERY_CAPACITY
                yield f"recharged to {self.battery}"
            else:
                steps = min(self.battery, self.distance)
                self.distance -= steps
                self.battery -= steps
                yield f"moved {steps}"


class Agent:
    """
    Stream the plan, run the trip, and handle messages at each safe point.
    """

    def __init__(self, narrator: Narrator, trip: Trip, inbox: Inbox) -> None:
        """
        :param narrator: Streams the plan description.
        :param trip:     The robot's work.
        :param inbox:    Messages from the operator.
        """
        self.narrator = narrator
        self.trip = trip
        self.inbox = inbox

    def run(self) -> str:
        """
        Run to the destination, or until a cancel arrives.

        :return: How the run ended.
        """
        print("Plan: ", end="", flush=True)
        for piece in self.narrator.stream():
            print(piece, end="", flush=True)
            if self.inbox.cancel_requested:
                print("\nCancelled before the trip started.")
                return "cancelled"
        print("\n")

        for step, progress in enumerate(self.trip.actions(), start=1):
            print(f"Step {step}: {progress} (distance {self.trip.distance}, battery {self.trip.battery})", flush=True)

            # Safe point: the action above is complete.
            for message in self.inbox.collect(after_step=step):
                if message.kind == "correction":
                    self.trip.distance += message.extra_steps
                    print(f"  Operator: destination moved {message.extra_steps} step(s) further. "
                          f"New distance {self.trip.distance}.")
                elif message.kind == "cancel":
                    print(f"  Stopped safely after step {step}: distance {self.trip.distance}, "
                          f"battery {self.trip.battery}.")
                    return "cancelled"

        return "arrived"


def main() -> None:
    """
    Run with scripted messages, or terminal corrections and cancellation.

    :return: None.
    """
    parser = argparse.ArgumentParser(description="Stream progress, accept corrections, and cancel safely.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scripted", action="store_true", help="Send a correction, then a cancel.")
    mode.add_argument("--interactive", action="store_true", help="Enter further N to extend the trip; cancel or Ctrl+C stops.")
    mode.add_argument("--model", help="Like --interactive, with a model streaming the plan.")
    args = parser.parse_args()

    scheduled = {2: Message("correction", extra_steps=2), 4: Message("cancel")} if args.scripted else {}
    inbox = Inbox(scheduled)
    signal.signal(signal.SIGINT, inbox.request_cancel)

    narrator: Narrator = OllamaNarrator(args.model) if args.model else ScriptedNarrator()
    agent = Agent(narrator, Trip(distance=3, battery=1), inbox)
    if not args.scripted:
        print("Enter further N to extend the trip, or cancel / Ctrl+C to stop.\n")
        threading.Thread(target=inbox.read_commands, daemon=True).start()

    try:
        status = agent.run()
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        parser.exit(1, f"Ollama HTTP {error.code}: {detail}\n")
    except (URLError, TimeoutError) as error:
        parser.exit(1, f"\nCould not run the model: {error}\n")

    print("Final status:", status)


if __name__ == "__main__":
    # Example commands:
    #   uv run python 27_streaming_and_interruption.py --scripted
    #   uv run python 27_streaming_and_interruption.py --interactive
    #   uv run python 27_streaming_and_interruption.py --model qwen
    main()
