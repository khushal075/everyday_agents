"""
33_agent_to_agent.py

Ask another team's agent for help, instead of calling one of your own tools.

Scenario:
    The same robot as examples 01-32: three moves from the lab, one battery
    unit, a battery that holds two. The robot needs a charging slot. Slots
    are managed by the building's dock scheduler, which is a separate agent
    run by another team. The robot cannot see inside it.

Goal:
    Find out what the other agent can do, give it a task, answer its
    questions, and get the result.

Difference from example 14:
    Example 14 used MCP: the robot called a tool with exact arguments and got
    an immediate answer. A tool does exactly what it is told.
    Another agent is different: it has its own rules, may ask a question
    before it can continue, can take time, and can say no.

Flow:
    1. Discovery: read the other agent's card, which lists its skills.
    2. If the needed skill is not listed, do not send the task.
    3. Send a task. Every message is JSON, as it would be over a network.
    4. Follow the task's state:
           submitted -> working -> input-required -> working -> completed or failed
    5. When the other agent needs input, answer it, then continue.
    6. Use the result, or handle the refusal.

New concepts:
    1. An agent card describes another agent: its name, skills and address.
    2. A task has a lifecycle; the caller follows its state.
    3. "input-required" lets the other agent ask a question mid-task.
    4. The other agent decides; "failed" with a reason is a normal answer.
    5. Messages cross a boundary as JSON: nothing is shared but what is sent.

Agent-to-agent protocols such as A2A define these ideas over HTTP. This
example keeps both agents in one process so the ideas are easy to follow.

Modes:
    --scenario booked          A slot is booked after one question.
    --scenario dock_full       The scheduler refuses: no slots left.
    --scenario unknown_skill   The robot asks for a skill the scheduler does not have.

Requirements:
    Python's standard library only.
"""

import argparse
import itertools
import json
from dataclasses import dataclass, field

BATTERY_CAPACITY = 2


@dataclass
class Task:
    """
    The scheduler's private record of one task. Only JSON messages leave it.
    """
    id: str
    skill: str
    state: str = "submitted"
    battery: int | None = None
    history: list[str] = field(default_factory=lambda: ["submitted"])

    def move_to(self, state: str) -> None:
        """
        Change state and remember the path taken.

        :param state: The new state.
        :return: None.
        """
        self.state = state
        self.history.append(state)


class DockSchedulerAgent:
    """
    Another team's agent. The robot only sees its card and its JSON replies.
    """

    CARD = {
        "name": "Dock Scheduler",
        "description": "Books charging slots at the building's docks.",
        "skills": [{"id": "book-charging-slot", "description": "Reserve a dock for a robot."}],
        "url": "local://dock-scheduler",
    }

    def __init__(self, free_slots: list[str]) -> None:
        """
        :param free_slots: Slots it can still give out.
        """
        self.free_slots = list(free_slots)
        self.tasks: dict[str, Task] = {}
        self.ids = itertools.count(1)

    def card(self) -> str:
        """
        :return: The agent card, as JSON.
        """
        return json.dumps(self.CARD)

    def receive(self, message: str) -> str:
        """
        Handle one JSON message and reply with the task's state.

        :param message: {"type": "create", "skill": ...} or {"type": "reply", "task_id": ..., "text": ...}
        :return: The task's state as JSON.
        """
        request = json.loads(message)

        if request["type"] == "create":
            task = Task(id=f"task-{next(self.ids)}", skill=request["skill"])
            self.tasks[task.id] = task
            task.move_to("working")
            # It decides it needs more information before it can book.
            task.move_to("input-required")
            return self.status(task, question="What is the robot's battery level, in units?")

        task = self.tasks[request["task_id"]]
        task.move_to("working")
        try:
            task.battery = int(request["text"])
        except ValueError:
            task.move_to("input-required")
            return self.status(task, question="Please give the battery level as a whole number.")

        if not self.free_slots:
            task.move_to("failed")
            return self.status(task, reason="No charging slots left today.")

        # Its own rule: robots with an empty battery get the earliest slot.
        slot = self.free_slots.pop(0) if task.battery == 0 else self.free_slots.pop()
        task.move_to("completed")
        return self.status(task, result={"dock": "east", "slot": slot})

    @staticmethod
    def status(task: Task, **extra: object) -> str:
        """
        :param task:  The task to describe.
        :param extra: A question, a reason, or a result.
        :return: The task's state as JSON.
        """
        return json.dumps({"task_id": task.id, "state": task.state, "history": task.history, **extra})


class RobotAgent:
    """
    The robot's agent: discovers the scheduler, sends it a task, and answers its questions.
    """

    def __init__(self, battery: int) -> None:
        """
        :param battery: What the robot knows about itself.
        """
        self.battery = battery

    def can_ask(self, card_json: str, skill: str) -> bool:
        """
        :param card_json: The other agent's card.
        :param skill:     The skill the robot needs.
        :return: True if the card lists that skill.
        """
        card = json.loads(card_json)
        skills = [entry["id"] for entry in card["skills"]]
        print(f"Discovered '{card['name']}' with skills: {', '.join(skills)}")
        return skill in skills

    def answer(self, question: str) -> str:
        """
        Answer the other agent's question from what the robot knows.

        :param question: The question it asked.
        :return: The answer text.
        """
        if "battery" in question.lower():
            return str(self.battery)
        return "unknown"

    def request(self, scheduler: DockSchedulerAgent, skill: str, max_turns: int = 4) -> None:
        """
        Run one task with the scheduler from start to finish.

        :param scheduler: The other agent.
        :param skill:     The skill to ask for.
        :param max_turns: Stop if the conversation goes on too long.
        :return: None.
        """
        if not self.can_ask(scheduler.card(), skill):
            print(f"Not sent: the scheduler has no '{skill}' skill. Find another agent or tool.")
            return

        reply = json.loads(scheduler.receive(json.dumps({"type": "create", "skill": skill})))
        for _ in range(max_turns):
            print(f"  {reply['task_id']}: {reply['state']}")

            if reply["state"] == "input-required":
                text = self.answer(reply["question"])
                print(f"    scheduler asks: {reply['question']}")
                print(f"    robot answers:  {text}")
                message = {"type": "reply", "task_id": reply["task_id"], "text": text}
                reply = json.loads(scheduler.receive(json.dumps(message)))
            elif reply["state"] in ("completed", "failed"):
                print(f"  Task path: {' -> '.join(reply['history'])}")
                if reply["state"] == "completed":
                    print(f"Booked: dock {reply['result']['dock']} at {reply['result']['slot']}.")
                else:
                    print(f"Refused: {reply['reason']} The robot will wait and ask again later.")
                return
        print("Stopped: the task did not finish within the turn limit.")


def main() -> None:
    """
    Ask the dock scheduler for a charging slot.

    :return: None.
    """
    parser = argparse.ArgumentParser(description="Delegate a task to another team's agent.")
    parser.add_argument("--scenario", choices=["booked", "dock_full", "unknown_skill"], default="booked")
    args = parser.parse_args()

    slots = [] if args.scenario == "dock_full" else ["10:15", "11:30"]
    skill = "repair-wheel" if args.scenario == "unknown_skill" else "book-charging-slot"
    print("Robot: distance 3, battery 1 of 2. It needs a charging slot.\n")
    RobotAgent(battery=1).request(DockSchedulerAgent(slots), skill)


if __name__ == "__main__":
    # Example commands:
    #   uv run python 33_agent_to_agent.py --scenario booked
    #   uv run python 33_agent_to_agent.py --scenario dock_full
    #   uv run python 33_agent_to_agent.py --scenario unknown_skill
    main()
