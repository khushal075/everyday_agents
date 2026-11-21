"""
- Measure concurrent HTTP submissions to a real local API process.
- Run a separate worker against an isolated SQLite workflow database.
- Verify terminal job states, telemetry coverage, and completion throughput.
- Estimate queue delay from component event timestamps.
"""

import argparse
import json
import math
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from production.category_04_evaluation_and_observability.metrics import MetricsAggregator
from production.store import FeedbackStore
from production.worker import FeedbackWorker

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE = "production.category_04_evaluation_and_observability.service_load"


@dataclass(frozen=True)
class SubmissionResult:
    """
    - Record a submission's HTTP duration and accepted job identifier.
    - Preserve a failure description when the request cannot be accepted.
    """

    job_id: str | None
    duration_ms: float
    error: str | None


def duration_summary(values: list[float]) -> dict[str, float] | None:
    """
    - Summarize a collection of durations in milliseconds.
    - Use nearest-rank p95 and return None for an empty collection.
    """
    if not values:
        return None
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "median": median(ordered),
        "p95": ordered[math.ceil(len(ordered) * 0.95) - 1],
        "max": ordered[-1],
    }


def stop_process(process: subprocess.Popen) -> None:
    """
    - Terminate a child process that is still running.
    - Escalate to kill after a bounded wait and reap the child.
    """
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    else:
        process.wait()


class ServiceLoadScenario:
    """
    - Own the isolated server, worker, credentials, and databases.
    - Measure a finite positive-feedback workload without approval waiting.
    - Shut down child processes before removing temporary files.
    """

    def __init__(self, requests: int, concurrency: int, timeout: float) -> None:
        """
        - Store workload and timeout limits.
        - Generate a credential used only by the local exercise.
        """
        self.requests = requests
        self.concurrency = concurrency
        self.timeout = timeout
        self.api_key = secrets.token_urlsafe(32)

    @contextmanager
    def services(self, directory: Path) -> Iterator[tuple[str, Path, Path]]:
        """
        - Apply migrations and start an API on an OS-assigned loopback port.
        - Start a persistent worker process and wait for both to be ready.
        - Guarantee cleanup if startup or workload execution fails.
        """
        database = directory / "feedback.sqlite3"
        event_database = directory / "telemetry.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            migrations = REPO_ROOT / "production/01_workflow_runtime/migrations"
            for migration in sorted(migrations.glob("*.sql")):
                connection.executescript(migration.read_text(encoding="utf-8"))

        environment = {
            **os.environ,
            "FEEDBACK_DB_PATH": str(database),
            "FEEDBACK_TELEMETRY_DB": str(event_database),
            "FEEDBACK_CREDENTIALS": json.dumps({
                self.api_key: {
                    "subject_id": "load-client",
                    "tenant_id": "load-tenant",
                    "permissions": ["submit_feedback", "read_job"],
                },
            }),
        }

        with ExitStack() as stack:
            listener = stack.enter_context(socket.socket())
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            base_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
            api_log = stack.enter_context((directory / "api.log").open("w+"))
            worker_log = stack.enter_context((directory / "worker.log").open("w+"))

            server = subprocess.Popen(
                [
                    sys.executable, "-m", "uvicorn", "production.api:app",
                    "--fd", str(listener.fileno()), "--log-level", "warning",
                ],
                cwd=REPO_ROOT, env=environment,
                pass_fds=(listener.fileno(),),
                stdout=api_log, stderr=subprocess.STDOUT,
            )
            stack.callback(stop_process, server)

            worker = subprocess.Popen(
                [
                    sys.executable, "-m", MODULE, "--worker",
                    "--database", str(database),
                ],
                cwd=REPO_ROOT, env=environment,
                stdout=worker_log, stderr=subprocess.STDOUT,
            )
            stack.callback(stop_process, worker)

            deadline = time.monotonic() + self.timeout
            while True:
                if server.poll() is not None or worker.poll() is not None:
                    api_log.seek(0)
                    worker_log.seek(0)
                    raise RuntimeError(
                        "Service startup failed.\n"
                        + api_log.read()[-4000:] + worker_log.read()[-4000:]
                    )
                try:
                    with urlopen(f"{base_url}/openapi.json", timeout=1) as response:
                        api_ready = response.status == 200
                except (URLError, TimeoutError):
                    api_ready = False

                if time.monotonic() >= deadline:
                    raise TimeoutError("Services did not become ready in time.")
                if api_ready and (directory / "worker.ready").exists():
                    break
                time.sleep(0.05)

            try:
                yield base_url, database, event_database
            finally:
                # Let an in-flight job finish and emit its events before shutdown.
                (directory / "worker.stop").touch()
                try:
                    worker.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    stop_process(worker)

    def submit(self, base_url: str) -> SubmissionResult:
        """
        - Send one authenticated feedback request through a real socket.
        - Measure response time including HTTP communication.
        - Capture request failures without retrying a submission.
        """
        request = Request(
            f"{base_url}/feedback",
            data=json.dumps({"text": "This is excellent"}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-API-Key": self.api_key,
            },
        )
        started = time.perf_counter()
        job_id = None
        error = None
        try:
            with urlopen(request, timeout=min(self.timeout, 10)) as response:
                payload = json.load(response)
                if response.status != 202:
                    raise ValueError(f"Unexpected HTTP status {response.status}")
                job_id = payload["job_id"]
                if not isinstance(job_id, str) or not job_id:
                    raise ValueError("The response contained an invalid job ID.")
        except HTTPError as failure:
            error = f"HTTP {failure.code}"
        except (URLError, TimeoutError, ValueError, KeyError, OSError) as failure:
            error = type(failure).__name__
            job_id = None

        return SubmissionResult(
            job_id, (time.perf_counter() - started) * 1000, error,
        )

    def run(self) -> dict[str, object]:
        """
        - Submit concurrent requests and wait for all accepted work to settle.
        - Verify successful jobs through HTTP and database records.
        - Calculate throughput and event-derived queue delay estimates.
        """
        with TemporaryDirectory(prefix="feedback-load-") as temporary:
            directory = Path(temporary)
            with self.services(directory) as (base_url, database, event_database):
                started = time.perf_counter()
                with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                    results = list(executor.map(
                        self.submit, [base_url] * self.requests,
                    ))

                accepted = {result.job_id for result in results if result.job_id}
                if len(accepted) != sum(result.job_id is not None for result in results):
                    raise AssertionError("The API returned duplicate job IDs.")

                deadline = time.monotonic() + self.timeout
                while True:
                    with closing(sqlite3.connect(database, timeout=5)) as connection:
                        rows = connection.execute(
                            """
                            SELECT job_id, status, action FROM feedback_jobs
                            WHERE tenant_id = 'load-tenant'
                            """
                        ).fetchall()
                    states = {row[0]: row[1] for row in rows}
                    if all(states.get(job_id) in {"completed", "failed"} for job_id in accepted):
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Accepted jobs did not finish in time.")
                    time.sleep(0.01)

                elapsed = time.perf_counter() - started
                if set(states) != accepted:
                    raise AssertionError(
                        "Some submissions have an ambiguous outcome; "
                        "database job IDs differ from acknowledged job IDs."
                    )
                completed = {job_id for job_id in accepted if states[job_id] == "completed"}

                # Verify API-visible state separately from the throughput timer.
                for job_id in completed:
                    request = Request(
                        f"{base_url}/jobs/{job_id}",
                        headers={"X-API-Key": self.api_key},
                    )
                    with urlopen(request, timeout=5) as response:
                        detail = json.load(response)
                    assert detail["job"]["status"] == "completed"
                    assert detail["job"]["action"] == "record"
                    assert detail["review"] is None

            # Services have stopped, so final worker events are available.
            events = MetricsAggregator(event_database).read_events()
            job_events = [event for event in events if event.job_id in accepted]
            completed_events = {
                event.job_id for event in job_events
                if event.stage == "worker.completed" and event.outcome == "passed"
            }
            assert completed_events == completed, "Completion telemetry is incomplete."

            queue_estimates: list[float] = []
            unusable_queue_samples = 0
            for job_id in completed:
                queued = next(
                    (event for event in job_events
                     if event.job_id == job_id and event.stage == "store.queued"),
                    None,
                )
                claimed = next(
                    (event for event in job_events
                     if event.job_id == job_id and event.stage == "store.claimed"),
                    None,
                )
                if queued is None or claimed is None:
                    unusable_queue_samples += 1
                    continue
                delay = (
                    datetime.fromisoformat(claimed.timestamp)
                    - datetime.fromisoformat(queued.timestamp)
                ).total_seconds() * 1000
                if delay < 0:
                    unusable_queue_samples += 1
                else:
                    queue_estimates.append(delay)

            with closing(sqlite3.connect(database)) as connection:
                assert connection.execute("SELECT COUNT(*) FROM review_records").fetchone()[0] == 0
                assert not connection.execute("PRAGMA foreign_key_check").fetchall()

            failures = sum(result.error is not None for result in results)
            return {
                "submitted": self.requests,
                "concurrency": self.concurrency,
                "accepted": len(accepted),
                "submission_failures": failures,
                "submission_failure_types": sorted({
                    result.error for result in results if result.error is not None
                }),
                "completed_jobs": len(completed),
                "failed_jobs": len(accepted - completed),
                "workload_seconds": elapsed,
                "completed_jobs_per_second": len(completed) / elapsed,
                "submission_http_latency_ms": duration_summary([
                    result.duration_ms for result in results
                ]),
                "observed_queue_delay_ms": duration_summary(queue_estimates),
                "queue_delay_samples": len(queue_estimates),
                "unusable_queue_delay_samples": unusable_queue_samples,
                "worker_processing_ms": duration_summary([
                    event.duration_ms for event in job_events
                    if event.stage == "worker.completed" and event.outcome == "passed"
                ]),
            }


def worker_loop(database: Path) -> None:
    """
    - Run a long-lived worker process for the load exercise.
    - Poll for work until the parent creates the stop marker.
    """
    worker = FeedbackWorker(FeedbackStore(database))
    (database.parent / "worker.ready").touch()
    while not (database.parent / "worker.stop").exists():
        worker.run_once()
        time.sleep(0.01)


def main() -> int:
    """
    - Accept workload size, HTTP concurrency, and a bounded completion wait.
    - Print a JSON report and return a failure code for unsuccessful work.
    - Support the internal worker subprocess entry point.
    """
    parser = argparse.ArgumentParser(description="Measure the local feedback service.")
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--database", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        if args.database is None:
            parser.error("The internal worker requires a database.")
        worker_loop(args.database)
        return 0

    if args.requests < 1 or args.concurrency < 1 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("requests, concurrency, and timeout must be positive and finite.")

    try:
        report = ServiceLoadScenario(
            args.requests, args.concurrency, args.timeout,
        ).run()
    except (OSError, ValueError, AssertionError, RuntimeError, sqlite3.Error) as error:
        print(f"Service load failed: {error}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["completed_jobs"] == args.requests else 1


if __name__ == "__main__":
    raise SystemExit(main())
