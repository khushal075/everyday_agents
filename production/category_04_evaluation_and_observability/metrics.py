"""
- Read structured events from the telemetry SQLite database.
- Group events by stage and summarize outcomes and durations.
- Count distinct completed jobs using tenant and job identifiers.
- Print the summary as JSON.
"""

import argparse
import json
import math
import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median

from pydantic import TypeAdapter, ValidationError

from production.category_04_evaluation_and_observability.telemetry import TraceEvent


@dataclass(frozen=True)
class StageMetrics:
    """
    - Summarize events recorded for one workflow stage.
    - Count failed expectations and execution errors separately.
    - Express failure rate as a fraction and durations in milliseconds.
    """

    event_count: int
    passed_count: int
    failed_count: int
    error_count: int
    failure_rate: float
    duration_min_ms: float
    duration_median_ms: float
    duration_p95_ms: float
    duration_max_ms: float


class MetricsAggregator:
    """
    - Read validated events from an existing telemetry database.
    - Deduplicate events by their event ID.
    - Calculate stage metrics and distinct completed job counts.
    """

    def __init__(self, database_path: Path) -> None:
        """
        - Store the telemetry database path.
        - Prepare validation for serialized TraceEvent records.

        :param database_path: Existing SQLite telemetry database.
        :return: None.
        """
        self.database_path = database_path
        self.adapter = TypeAdapter(TraceEvent)

    def read_events(self) -> list[TraceEvent]:
        """
        - Open the database in read-only mode.
        - Validate each event and its duration before aggregation.
        - Reject conflicting records that share an event ID.

        :return: Validated events with unique event IDs.
        """
        database_uri = self.database_path.resolve().as_uri() + "?mode=ro"
        events: dict[str, TraceEvent] = {}

        with closing(
            sqlite3.connect(database_uri, uri=True, timeout=5.0)
        ) as connection:
            rows = connection.execute(
                "SELECT event_id, payload FROM telemetry_events ORDER BY rowid"
            )
            for stored_id, payload in rows:
                event = self.adapter.validate_json(payload)
                if event.event_id != stored_id:
                    raise ValueError(
                        f"Stored event ID differs from payload ID: {stored_id}"
                    )
                if not math.isfinite(event.duration_ms) or event.duration_ms < 0:
                    raise ValueError(f"Invalid duration for event {event.event_id}")
                if event.attempt < 1:
                    raise ValueError(f"Invalid attempt for event {event.event_id}")

                previous = events.get(event.event_id)
                if previous is not None and previous != event:
                    raise ValueError(f"Conflicting event ID: {event.event_id}")
                events[event.event_id] = event

        return list(events.values())

    def summarize_stage(self, events: list[TraceEvent]) -> StageMetrics:
        """
        - Count stage outcomes and calculate duration statistics.
        - Calculate p95 using the nearest-rank method.
        - Require at least one event.

        :param events: Events belonging to one stage.
        :return: Outcome counts, failure rate, and duration statistics.
        """
        if not events:
            raise ValueError("A stage must contain at least one event.")

        durations = sorted(event.duration_ms for event in events)
        count = len(events)
        passed = sum(event.outcome == "passed" for event in events)
        failed = sum(event.outcome == "failed" for event in events)
        errors = sum(event.outcome == "error" for event in events)
        p95_index = math.ceil(count * 0.95) - 1

        return StageMetrics(
            event_count=count,
            passed_count=passed,
            failed_count=failed,
            error_count=errors,
            failure_rate=(failed + errors) / count,
            duration_min_ms=durations[0],
            duration_median_ms=median(durations),
            duration_p95_ms=durations[p95_index],
            duration_max_ms=durations[-1],
        )

    def summarize(self) -> dict[str, object]:
        """
        - Group all saved events by stage.
        - Count successful worker completions once per tenant and job.
        - Build a JSON-serializable report.

        :return: Event totals, completed job count, and stage metrics.
        """
        events = self.read_events()
        stages: dict[str, list[TraceEvent]] = defaultdict(list)
        completed_jobs: set[tuple[str | None, str]] = set()

        for event in events:
            stages[event.stage].append(event)
            if (
                event.stage == "worker.completed"
                and event.outcome == "passed"
                and event.job_id is not None
            ):
                completed_jobs.add((event.tenant_id, event.job_id))

        return {
            "event_count": len(events),
            "completed_job_count": len(completed_jobs),
            "stages": {
                stage: asdict(self.summarize_stage(stage_events))
                for stage, stage_events in sorted(stages.items())
            },
        }


def main() -> int:
    """
    - Accept the telemetry database path.
    - Print aggregated metrics as JSON.
    - Return a nonzero exit code when events cannot be read.

    :return: Zero on success or one on a read or validation failure.
    """
    parser = argparse.ArgumentParser(description="Summarize saved workflow telemetry.")
    parser.add_argument(
        "--database", type=Path, default=Path("telemetry.sqlite3"),
    )
    args = parser.parse_args()

    try:
        report = MetricsAggregator(args.database).summarize()
    except (sqlite3.Error, ValidationError, ValueError, OSError) as error:
        print(f"Metrics error: {error}")
        return 1

    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
