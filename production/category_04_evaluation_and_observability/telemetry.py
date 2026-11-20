"""
    - Emit structured events as one JSON object per line.
    - Associate each events with a run, stage, attempt and outcome.
    - Write to stderr by default so stdout can show evaluation results.
"""

import json
import sys
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
    def __init__(self, stream: Optional[TextIO] = None) -> None:
        """
            - Store the destination stream
            - Use stderr when no stream is supplied
        """
        self.stream = stream if stream is not None else sys.stderr


    def emit(
        self,
        *,
        run_id: str,
        stage: str,
        outcome: EventOutcome,
        duration_ms: float,
        job_id: Optional[str] = None,
        team_id: Optional[str] = None,
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
        :param team_id: Tenant that owns the job, when available.
        :param attempt: Execution attempt number, starting at 1.
        :param error_type: Exception class name when stage raises an error.

        :return: None
        """
        event = TraceEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            run_id=run_id,
            job_id=job_id,
            tenant_id=team_id,
            stage=stage,
            attempt=attempt,
            outcome=outcome,
            duration_ms=round(duration_ms, 3),
            error_type=error_type,
        )
        self.stream.write(json.dumps(asdict(event), allow_nan=False) + "\n")
        self.stream.flush()
