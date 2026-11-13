"""
12_checkpoints_and_resumable_approval.py

Save a delivery request, approve it in a separate process, and resume it later.

Each command starts a new process. A JSON checkpoint carries the state between commands.
The deivery is simulated: Saving its completion record is the entire action.

No external service is called.

Uses only the python standard library. Run one commnd at a time.
"""

import argparse
import json
from dataclasses import dataclass, asdict, replace
from pathlib import Path
from typing import Literal

Status = Literal["awaiting_approval", "approved", "rejected", "delivered"]

@dataclass(frozen=True)
class DeliveryRequest:
    """
    The exact action a human is being asked to approve.
    """
    operation_id: str
    package: str
    destination: str


@dataclass(frozen=True)
class Checkpoint:
    """
    The saved progress and the request a human approves.
    """
    request: DeliveryRequest
    status: Status = "awaiting_approval"
    approved_request: DeliveryRequest | None = None


class CheckpointStore:
    """
    Save and load one checkpoint from local JSON file.
    """
    def __init__(self, path: Path) -> None:
        """
        Remember where this workflow's checkpoint lives.

        :param path:
        """
        self.path = path

    def load(self) -> Checkpoint:
        """
        Rebuild the checkpoint and its request from JSON.

        :return:
        """
        data = json.loads(self.path.read_text(encoding="utf-8"))
        approved = data["approved_request"]

        return Checkpoint(
            request=DeliveryRequest(**data["request"]),
            status=data["status"],
            approved_request=DeliveryRequest(**approved) if approved is not None else None,
        )

    def save(self, checkpoint: Checkpoint) -> None:
        """
        Write a complete temporary file, then replace the checkpoint.
        :param checkpoint:
        :return:
        """
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(
            json.dumps(asdict(checkpoint), indent=4) + "\n",
        )
        temporary.replace(self.path)


class Agent:
    """
    Create, approve and resume a simulated delivery workflow.
    """
    def __init__(self, store: CheckpointStore) -> None:
        """
        Connect the agent to its persistent checkpoint store.

        :param store:
        """
        self.store = store

    def start(self, delivery_request: DeliveryRequest) -> str:
        """
        Save the proposed action and exit before delivery.

        :param delivery_request:
        :return:
        """
        if self.store.path.exists():
            raise FileExistsError("Checkpoint already exists; use a new --checkpoint path")

        self.store.save(Checkpoint(request=delivery_request))
        return "Request saved. Awaiting human approval."

    def approve(self) -> str:
        """
        Show the exact action and save the human's decision.
        :return:
        """
        checkpoint = self.store.load()
        if checkpoint.status != "awaiting_approval":
            return f"Nothing to approve. Current status: {checkpoint.status}"

        request = checkpoint.request
        print(f"Operation: {request.operation_id}")
        print(f"Package: {request.package}")
        print(f"Destination: {request.destination}")

        try:
            answer = input("Approve this exact delivery? [yes/no]: ")
        except EOFError:
            return "No decision received. Still awaiting approval."

        if answer == "no":
            self.store.save(replace(checkpoint, status="rejected"))
            return "Delivery rejected."

        if answer != "yes":
            return "Please enter yes or no. Still awaiting approval."

        self.store.save(
            replace(checkpoint, status="approved", approved_request=request)
        )

        return "Approval saved. Run resume to continue"

    def resume(self) -> str:
        """
        Deliver only when the saved approval matches the current request.

        :return:
        """
        checkpoint = self.store.load()

        if checkpoint.status == "delivered":
            return "Already delivered."

        if checkpoint.status != "approved":
            return f"Delivery blocked. Current status: {checkpoint.status}"

        if checkpoint.approved_request != checkpoint.request:
            return f"Delivery blocked. The request differs from the approved request"

        # The completion record is simulated delivery. There is no separate
        # external action between executing it and saving the checkpoint.

        self.store.save(replace(checkpoint, status="delivered"))
        return f"Delivered {checkpoint.request.package} to {checkpoint.request.destination}"

def main():
    """
    Run one command against the same checkpoint across process restarts.

    :return:
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "approve", "resume"])
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("12_delivery_checkpoint.json"),
    )
    args = parser.parse_args()
    agent = Agent(CheckpointStore(args.checkpoint))

    try:
        if args.command == "start":
            message = agent.start(
                DeliveryRequest("delivery-001", "robot battery", "Room D")
            )
        elif args.command == "approve":
            message = agent.approve()
        else:
            message = agent.resume()
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Checkpoint error: {error}\n")

    print(message)


if __name__ == "__main__":
    """
        uv run python 12_checkpoints_and_resumable_approval.py start
        uv run python 12_checkpoints_and_resumable_approval.py resume
        uv run python 12_checkpoints_and_resumable_approval.py approve
        uv run python 12_checkpoints_and_resumable_approval.py resume
        uv run python 12_checkpoints_and_resumable_approval.py resume
    """
    main()
