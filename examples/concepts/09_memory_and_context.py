"""
09_memory_and_context.py

Answer robot questions and resolve simple follow-ups using topic memory.

The agent remembers one topic in memory.
Each model request contains
    - The current question
    - Resolved topic
    - Relevant manual passages

Start a new process to clear the memory.
"""

import argparse
import re
import json
from dataclasses import dataclass
from typing import List, Literal
from urllib.error import HTTPError, URLError
from urllib.request import urlopen, Request

Topic = Literal["battery", "movement"]

MANUAL: dict[Topic, str] = {
    "battery": (
        "Connect the robot to its charging dock to recharge the battery. "
        "A full battery provides enough power for two moves."
    ),
    "movement": "Move one step towards the destination when the path is clear.",
}

@dataclass
class Memory:
    """
    Keep the most recent topic used in successful model request.
    """
    last_topic: Topic | None = None


@dataclass(frozen=True)
class Context:
    """
    Information supplied to the model for one question.
    """
    question: str
    topic: Topic
    passage: str


class OllamaGenerator:
    """
    Answer a question using the supplied manual passage.
    """
    def __init__(self, model: str) -> None:
        """
        Stored the installed Ollama model name.

        :param model:
        """
        self.model = model

    def generate(self, context: Context) -> str:
        """
        Send one turn's context and return the generated answer.

        :param context:
        :return:
        """
        payload = {
            "model": self.model,
            "system":" ".join([
                "Answer using only the manual passage.",
                "Use the topic to resolve reference in the question. ",
                "If the passage does not answer the question, say so."
            ]),
            "prompt": " ".join([
                f"Topic: {context.topic}\n",
                f"Manual passage: {context.passage}\n",
                f"Question: {context.question}",
            ]),
            "stream": False
        }

        request = Request(
            url="http://localhost:11434/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

        with urlopen(request) as response:
            answer = json.load(response)['response']

        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("The model returned no answer text")

        return answer.strip()

class Agent:
    """
    Resolve the topic, build context, and remember it for the next turn.
    """
    def __init__(self, generator: OllamaGenerator) -> None:
        """
        Start with the model connection and empty memory.

        :param generator:
        """
        self.generator = generator
        self.memory = Memory()

    def run(self, question: str) -> str:
        """
        Answer using an explicit topic or a simple reference to memory.

        :param question:
        :return:
        """
        words = set(re.findall(r"[a-z]+", question.lower()))
        mentions_battery = bool(words & {"battery", "recharge", "charging"})
        mentions_movement = bool(words & {"move", "movement", "destination"})

        # If the question names both topics, ask the user to narrow it down.
        if mentions_battery and mentions_movement:
            return "Are you asking about the battery or movement?"

        # An explicit topic takes precedence over remembered topic.
        if mentions_battery:
            topic = "battery"
        elif mentions_movement:
            topic = "movement"
        elif "it" in words and self.memory.last_topic is not None:
            topic = self.memory.last_topic
            print(f"Using remembered topic: {topic}")
        else:
            return "Which topic do you mean: battery or movement?"

        context = Context(question, topic, MANUAL[topic])
        print(f"Context sent to Qwen: {context}")
        answer = self.generator.generate(context)

        # Keep the topic only after the model request succeeds.
        self.memory.last_topic = topic
        return answer


def main():
    """
    Keep one agent instance alive across questions in a terminal session.
    :return:
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    agent = Agent(OllamaGenerator(args.model))
    print("Ask about the robot. Type 'quit' to exit.")

    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("Exiting.")
            break

        if question.lower() == "quit":
            break

        if not question:
            continue

        try:
            print("Agent: ", agent.run(question))
        except HTTPError as error:
           details = error.read().decode("utf-8", errors="replace")
           print(f"Ollama HTTP {error.code}: {details}")

        except (URLError, TimeoutError, ValueError, KeyError, TypeError) as error:
            print(f"Could not generate an answer: {error}")


if __name__ == "__main__":
    # uv run python 09_memory_and_context.py --model qwen
    # How do i recharge the battery?
    # how long does it last ?
    main()
