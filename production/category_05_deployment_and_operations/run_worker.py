"""
- Poll the persistent feedback queue until shutdown is requested.
- Publish a heartbeat before and after each attempt.
- Finish the current attempt before a graceful shutdown.
"""

import argparse
import json
import math
import os
import signal
import threading
from pathlib import Path
from time import time

from production.store import FeedbackStore
from production.worker import FeedbackWorker


class WorkerRunner:
    """
    - Own the worker loop and shutdown handlers.
    - Publish atomically replaced heartbeat files.
    """

    def __init__(
        self, database_path: Path, heartbeat_path: Path, poll_seconds: float,
    ) -> None:
        """
        - Prepare the worker and stop event.
        - Require a finite, positive polling interval.
        """
        if not math.isfinite(poll_seconds) or poll_seconds <= 0:
            raise ValueError("poll_seconds must be finite and positive.")
        self.worker = FeedbackWorker(FeedbackStore(database_path))
        self.heartbeat_path = heartbeat_path
        self.poll_seconds = poll_seconds
        self.stopping = threading.Event()

    def request_shutdown(self, signum: int, frame: object) -> None:
        """
        - Handle SIGTERM or SIGINT by requesting shutdown.
        - Leave the current processing attempt to finish.
        """
        self.stopping.set()

    def write_heartbeat(self) -> None:
        """
        - Write the process ID and Unix timestamp.
        - Replace the heartbeat file atomically.
        """
        temporary = self.heartbeat_path.with_name(
            f"{self.heartbeat_path.name}.{os.getpid()}.tmp"
        )
        try:
            temporary.write_text(
                json.dumps({"pid": os.getpid(), "timestamp": time()}),
                encoding="utf-8",
            )
            temporary.replace(self.heartbeat_path)
        finally:
            temporary.unlink(missing_ok=True)

    def run(self) -> None:
        """
        - Process eligible jobs and refresh the heartbeat around each attempt.
        - Remove the heartbeat and restore signal handlers on exit.
        """
        previous_term = signal.signal(signal.SIGTERM, self.request_shutdown)
        previous_int = signal.signal(signal.SIGINT, self.request_shutdown)
        try:
            while not self.stopping.is_set():
                self.write_heartbeat()
                self.worker.run_once()
                self.write_heartbeat()
                self.stopping.wait(self.poll_seconds)
        finally:
            self.heartbeat_path.unlink(missing_ok=True)
            signal.signal(signal.SIGTERM, previous_term)
            signal.signal(signal.SIGINT, previous_int)


def main() -> int:
    """
    - Read database, heartbeat, and polling settings.
    - Run the worker until a signal requests shutdown.
    """
    parser = argparse.ArgumentParser(description="Run the feedback worker.")
    parser.add_argument("--database", type=Path, default=Path(
        os.environ.get("FEEDBACK_DB_PATH", "feedback-runtime.sqlite3"),
    ))
    parser.add_argument("--heartbeat", type=Path, default=Path(
        os.environ.get("FEEDBACK_WORKER_HEARTBEAT", "worker-heartbeat.json"),
    ))
    parser.add_argument("--poll-seconds", type=float, default=0.2)
    args = parser.parse_args()
    WorkerRunner(args.database, args.heartbeat, args.poll_seconds).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
