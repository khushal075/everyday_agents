"""
23_long_term_memory.py

Let the robot remember useful facts between sessions, correct them, and forget them.

Scenario:
    The same robot as examples 01-22. Over several working sessions it learns
    things about its building: where the charging dock is, that a path is
    temporarily blocked. The demo reloads disk-backed memory for each session in one process.
    Separate CLI commands demonstrate the same persistence across processes.

Goal:
    Recall the right facts in a later session, replace facts that became
    outdated, and drop facts that should no longer be used.

Difference from examples 09 and 12:
    Example 09 remembered one topic inside a single session.
    Example 12 saved where a task had stopped, so it could resume.
    Here the robot saves knowledge that is useful for future, unrelated tasks.

Flow:
    Session 1: learn two facts and save them.
    Session 2: a fresh store loads the file and recalls them.
    Session 3: an operator corrects the dock location; the old value is kept
               as history but no longer recalled.
    Session 4: the blocked-path fact expires; an operator asks to forget
               the dock history entirely.

New concepts:
    1. Long-term memory is stored outside the process (here, a JSON file).
    2. Each fact records its source, so you know why the robot believes it.
    3. A correction replaces a fact instead of adding a conflicting second one.
    4. Some facts should expire; old ones must not be recalled forever.
    5. Forgetting deletes the fact and its history when asked to.
    6. Only confirmed facts are saved. Guesses are not memories.

Modes:
    1. demo                     Run four sessions, reloading memory from disk each time.
    2. remember KEY VALUE       Save a fact from the command line.
    3. recall WORDS...          Find facts whose key or value contain the words.
    4. forget KEY               Delete a fact and its history.
    5. show                     Print everything stored, including history.

Requirements:
    Python's standard library only.
"""

import argparse
import json
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Fact:
    """
    One remembered fact, where it came from, and the values it replaced.
    """
    key: str
    value: str
    source: str
    learned_in_session: int
    expires_after_session: int | None = None
    history: list[str] = field(default_factory=list)


class MemoryStore:
    """
    Keep facts in a JSON file so a later process can read them.
    """

    def __init__(self, path: Path) -> None:
        """
        Load existing facts from the file, if there is one.

        :param path: Where the memory file lives.
        """
        self.path = path
        self.facts: dict[str, Fact] = {}
        if path.exists():
            for key, data in json.loads(path.read_text()).items():
                self.facts[key] = Fact(**data)

    def save(self) -> None:
        """
        Write every fact to the file.

        :return: None.
        """
        data = {key: asdict(fact) for key, fact in self.facts.items()}
        self.path.write_text(json.dumps(data, indent=2))

    def remember(self, key: str, value: str, source: str, session: int,
                 expires_after_session: int | None = None) -> None:
        """
        Save a fact, or correct it if the key already exists.

        A correction moves the old value into history, so the robot never
        holds two different answers for the same question.

        :param key:                   A short name, e.g. dock-location.
        :param value:                 What is true.
        :param source:                Who or what confirmed it.
        :param session:               The session it was learned in.
        :param expires_after_session: Stop recalling it after this session, if set.
        :return: None.
        """
        old = self.facts.get(key)
        history = list(old.history) if old is not None else []
        if old is not None and old.value != value:
            history = old.history + [f"{old.value} (from {old.source}, session {old.learned_in_session})"]
            print(f"  Corrected {key}: '{old.value}' -> '{value}'")
        else:
            print(f"  Remembered {key}: '{value}'")

        self.facts[key] = Fact(key, value, source, session, expires_after_session, history)
        self.save()

    def recall(self, words: list[str], session: int) -> list[Fact]:
        """
        Return current facts whose key or value contains any of the words.

        Expired facts are skipped. Old values in history are never returned.

        :param words:   Words to look for.
        :param session: The current session, used to check expiry.
        :return: Matching facts.
        """
        # Common words like "is" or "the" would match almost any fact.
        filler = {"a", "an", "the", "is", "are", "where", "what", "how", "do", "does"}
        wanted = {word.lower() for word in words} - filler
        matches = []
        for fact in self.facts.values():
            if fact.expires_after_session is not None and session > fact.expires_after_session:
                continue
            text = f"{fact.key} {fact.value}".lower().replace("-", " ")
            if wanted & set(text.split()):
                matches.append(fact)
        return matches

    def forget(self, key: str) -> bool:
        """
        Delete a fact and its history.

        :param key: The fact to delete.
        :return: True if it existed.
        """
        if key not in self.facts:
            return False
        del self.facts[key]
        self.save()
        print(f"  Forgot {key} and its history.")
        return True

    def expire(self, session: int) -> None:
        """
        Delete facts whose expiry session has passed.

        :param session: The current session.
        :return: None.
        """
        expired = [
            key for key, fact in self.facts.items()
            if fact.expires_after_session is not None and session > fact.expires_after_session
        ]
        for key in expired:
            del self.facts[key]
            print(f"  Expired {key}.")
        if expired:
            self.save()


class Session:
    """
    One working session: a fresh MemoryStore that loads whatever was saved before.
    """

    def __init__(self, number: int, path: Path) -> None:
        """
        Start a session by loading memory from disk.

        :param number: The session number.
        :param path:   The memory file.
        """
        self.number = number
        self.memory = MemoryStore(path)
        print(f"\nSession {number}: loaded {len(self.memory.facts)} fact(s) from disk.")

    def ask(self, question: str) -> None:
        """
        Recall facts related to a question and print them.

        :param question: What the robot wants to know.
        :return: None.
        """
        words = [word.strip("?.,").lower() for word in question.split()]
        facts = self.memory.recall(words, self.number)
        print(f"  Q: {question}")
        if not facts:
            print("     nothing remembered")
        for fact in facts:
            print(f"     {fact.key} = {fact.value}  (source: {fact.source}, session {fact.learned_in_session})")


class Demo:
    """
    Run four sessions in order, each as if it were a new process.
    """

    def __init__(self, path: Path) -> None:
        """
        :param path: The memory file shared by all sessions.
        """
        self.path = path

    def run(self) -> None:
        """
        Learn, recall, correct, expire and forget.

        :return: None.
        """
        first = Session(1, self.path)
        first.memory.remember("dock-location", "north wall", source="robot saw it", session=1)
        first.memory.remember("path-b", "blocked by boxes", source="operator", session=1,
                              expires_after_session=2)
        # A guess is not saved: the robot only thinks the lab door might be locked.
        print("  Not saved: 'lab door may be locked' (a guess, not a confirmed fact)")

        second = Session(2, self.path)
        second.ask("Where is the dock?")
        second.ask("Is path b blocked?")

        third = Session(3, self.path)
        third.memory.remember("dock-location", "east wall", source="operator", session=3)
        third.ask("Where is the dock?")
        third.ask("Is path b blocked?")

        fourth = Session(4, self.path)
        fourth.memory.expire(4)
        fourth.memory.forget("dock-location")
        fourth.ask("Where is the dock?")


def main() -> None:
    """
    Run the demo, or work with the memory file directly.

    :return: None.
    """
    parser = argparse.ArgumentParser(description="Remember, recall, correct and forget facts.")
    parser.add_argument("--memory", type=Path, help="Memory file (default: a new temporary file for demo).")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo", help="Run four sessions in order.")
    remember = commands.add_parser("remember", help="Save or correct a fact.")
    remember.add_argument("key")
    remember.add_argument("value")
    recall = commands.add_parser("recall", help="Find facts containing these words.")
    recall.add_argument("words", nargs="+")
    forget = commands.add_parser("forget", help="Delete a fact and its history.")
    forget.add_argument("key")
    commands.add_parser("show", help="Print every stored fact.")
    args = parser.parse_args()

    if args.command == "demo":
        path = args.memory or Path(tempfile.mkdtemp()) / "robot_memory.json"
        print(f"Memory file: {path}")
        Demo(path).run()
        return

    path = args.memory or Path("23_robot_memory.json")
    memory = MemoryStore(path)
    if args.command == "remember":
        memory.remember(args.key, args.value, source="command line", session=0)
    elif args.command == "recall":
        for fact in memory.recall(args.words, session=0):
            print(f"{fact.key} = {fact.value}  (source: {fact.source})")
    elif args.command == "forget":
        if not memory.forget(args.key):
            parser.exit(1, f"No fact named {args.key}.\n")
    else:
        print(json.dumps({key: asdict(fact) for key, fact in memory.facts.items()}, indent=2))


if __name__ == "__main__":
    # Example commands:
    #   uv run python 23_long_term_memory.py demo
    #   uv run python 23_long_term_memory.py remember dock-location "north wall"
    #   uv run python 23_long_term_memory.py recall dock
    #   uv run python 23_long_term_memory.py remember dock-location "east wall"
    #   uv run python 23_long_term_memory.py show
    #   uv run python 23_long_term_memory.py forget dock-location
    main()
