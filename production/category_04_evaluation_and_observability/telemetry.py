"""
    - Emit structured events as one JSON object per line.
    - Associate each events with a run, stage, attempt and outcome.
    - Write to stderr by default so stdout can show evaluation results.
"""

import os
import threading
import sqlite3
from collections.abc import Iterator
import json
import sys
from pathlib import Path
from time import perf_counter
from uuid import uuid4
from contextlib import contextmanager, closing
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Literal, TextIO, Optional

EventOutcome = Literal["passed", "failed", "error"]

@dataclass(frozen=True)
class TraceEvent:
    """
        - Describe one completed stage of the workflow.
        - Record duration in milliseconds.
        - Include identifiers that help correlate events across components.
    """
    event_id: str
    timestamp: str
    run_id: str
    job_id: Optional[str]
    tenant_id: Optional[str]
    stage: str
    attempt: int
    outcome: EventOutcome
    duration_ms: float
    error_type: Optional[str]

class Telemetry:
    """
        - Serialize workflow events into JSON lines.
        - Accept a stream so callers can select stderr or an open log file.
    """
    def __init__(self, stream: Optional[TextIO] = None, database_path: Optional[Path] = None) -> None:
        """
            - Configure stream output and optional persistent event storage.
            - Create the telemetry table when a database path is supplied.

        :param stream: Writable text stream. Default to stderr.
        :param database_path: Separate SQLite database file for telemetry events.

        :return: None
        """
        self._stream_lock = threading.Lock()
        self.stream = stream if stream is not None else sys.stderr
        self.database_path = Path(database_path) if database_path is not None else None
        if self.database_path is not None:
            with closing(sqlite3.connect(self.database_path, timeout=5.0)) as connection:
                with connection:
                    connection.execute(
                        """
                            CREATE TABLE IF NOT EXISTS telemetry_events (
                                event_id TEXT PRIMARY KEY NOT NULL,
                                payload TEXT NOT NULL
                            )
                        """
                    )



    def emit(
        self,
        *,
        run_id: str,
        stage: str,
        outcome: EventOutcome,
        duration_ms: float,
        job_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        attempt: int = 1,
        error_type: Optional[str] = None,
    )-> None:
        """
            Emit one structured workflow event.
                - Build one event with the current UTC timestamp.
                - Write one JSON line and flush the output stream.

        :param run_id: Identifier shared by the events from same workflow run.
        :param stage: Workflow stage that produced the event.
        :param outcome: Whether the staged passed, failed or raise an error.
        :param duration_ms: Time spent in stage, measured in milliseconds.
        :param job_id: Persistent feedback job ID, when available.
        :param tenant_id: Tenant that owns the job, when available.
        :param attempt: Execution attempt number, starting at 1.
        :param error_type: Exception class name when stage raises an error.

        :return: None
        """
        event = TraceEvent(
            event_id=uuid4().hex,
            timestamp=datetime.now(timezone.utc).isoformat(),
            run_id=run_id,
            job_id=job_id,
            tenant_id=tenant_id,
            stage=stage,
            attempt=attempt,
            outcome=outcome,
            duration_ms=round(duration_ms, 3),
            error_type=error_type,
        )
        payload = json.dumps(asdict(event), allow_nan=False)
        if self.database_path is not None:
            with closing(sqlite3.connect(self.database_path, timeout=5.0)) as connection:
                with connection:
                    connection.execute(
                        """
                            INSERT INTO telemetry_events (event_id, payload) VALUES (?, ?)
                        """, (event.event_id, payload),
                    )
        with self._stream_lock:
            self.stream.write(payload + "\n")
            self.stream.flush()


    @contextmanager
    def measure(
        self,
        *,
        run_id: str,
        stage: str,
        job_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        attempt: int = 1,
    ) -> Iterator[None]:
        """
            - Measure the operation inside the context block.
            - Emit success when it finishes or an error when it raises.
            - Propagate the original operation execution.

        :param run_id: Identifier shared by related events.
        :param stage: Name of the measured operation.
        :param job_id: Persistent Job identifier, when available.
        :param tenant_id: tenant that owns the job.
        :param attempt: Execution attempt number, starting at 1.

        :return: A context manager around the measured operations.
        """
        started = perf_counter()
        outcome = "passed"
        error_type = None
        try:
            yield
        except Exception as error:
            outcome = "error"
            error_type = type(error).__name__
            raise
        finally:
            self.safe_emit(
                run_id=run_id, stage=stage, job_id=job_id,
                tenant_id=tenant_id, attempt=attempt, outcome=outcome,
                duration_ms=(perf_counter() - started) * 1000,
                error_type=error_type,
            )

    @classmethod
    def from_environment(cls) -> "Telemetry":
        """
        - Read the shared event destination from FEEDBACK_TELEMETRY_DB.
        - Use stream output when the environment variable is absent.
        """
        destination = os.environ.get("FEEDBACK_TELEMETRY_DB")
        return cls(database_path=Path(destination) if destination else None)

    def safe_emit(
        self, *, run_id: str, stage: str, outcome: EventOutcome,
        duration_ms: float, job_id: str | None = None,
        tenant_id: str | None = None, attempt: int = 1,
        error_type: str | None = None,
    ) -> None:
        """
        - Emit runtime telemetry without changing the business operation result.
        - Report telemetry failures to stderr using the exception type.
        """
        try:
            self.emit(
                run_id=run_id, stage=stage, outcome=outcome,
                duration_ms=duration_ms, job_id=job_id, tenant_id=tenant_id,
                attempt=attempt, error_type=error_type,
            )
        except Exception as error:
            print(f"Telemetry write failed: {type(error).__name__}", file=sys.stderr)
