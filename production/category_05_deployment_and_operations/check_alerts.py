"""
- Evaluate local job-state and recent telemetry thresholds.
- Print active alert findings as JSON.
- Return 0 for clear, 1 for active alerts, and 2 for checker failure.
"""

import argparse
import json
import os
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from production.category_04_evaluation_and_observability.metrics import MetricsAggregator


class AlertRules(BaseModel):
    """
    - Validate the alert window, sample floor, and thresholds.
    - Reject unknown configuration fields and nonfinite thresholds.
    """

    model_config = ConfigDict(extra="forbid")
    window_seconds: FiniteFloat = Field(gt=0)
    minimum_events: int = Field(ge=1)
    failure_rate: FiniteFloat = Field(ge=0, le=1)
    api_p95_ms: FiniteFloat = Field(gt=0)
    queued_age_seconds: FiniteFloat = Field(gt=0)
    expired_lease_grace_seconds: FiniteFloat = Field(ge=0)
    approval_age_seconds: FiniteFloat = Field(gt=0)


class AlertChecker:
    """
    - Combine durable job-state checks with windowed event summaries.
    - Report the rule and number or rate that crossed its threshold.
    """

    def __init__(self, database: Path, telemetry: Path, rules: AlertRules) -> None:
        """
        - Store workflow, event database, and validated rule settings.
        """
        self.database = database
        self.telemetry = telemetry
        self.rules = rules

    def check(self) -> list[dict[str, object]]:
        """
        - Inspect eligible queued jobs, expired leases, and approval waiting.
        - Evaluate recent stage failures and API p95 latency.
        """
        alerts: list[dict[str, object]] = []
        uri = self.database.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
            now = connection.execute(
                "SELECT (julianday('now') - 2440587.5) * 86400"
            ).fetchone()[0]
            queries = (
                (
                    "old_queued_jobs",
                    """
                    SELECT COUNT(*) FROM feedback_jobs
                    WHERE status = 'queued' AND retry_at <= ?
                      AND (julianday('now') - julianday(created_at)) * 86400 > ?
                    """,
                    (now, self.rules.queued_age_seconds),
                ),
                (
                    "expired_worker_leases",
                    """
                    SELECT COUNT(*) FROM feedback_jobs
                    WHERE status = 'running' AND lease_expires_at < ?
                    """,
                    (now - self.rules.expired_lease_grace_seconds,),
                ),
                (
                    "old_approval_requests",
                    """
                    SELECT COUNT(*) FROM feedback_jobs
                    WHERE status = 'awaiting_approval'
                      AND (julianday('now') - julianday(updated_at)) * 86400 > ?
                    """,
                    (self.rules.approval_age_seconds,),
                ),
            )
            for rule, query, parameters in queries:
                count = connection.execute(query, parameters).fetchone()[0]
                if count:
                    alerts.append({"rule": rule, "jobs": count})

        aggregator = MetricsAggregator(self.telemetry)
        cutoff = datetime.now(timezone.utc).timestamp() - self.rules.window_seconds
        stages = defaultdict(list)
        for event in aggregator.read_events():
            timestamp = datetime.fromisoformat(event.timestamp)
            if timestamp.tzinfo is None:
                raise ValueError("Telemetry timestamp must contain a timezone.")
            if timestamp.timestamp() >= cutoff:
                stages[event.stage].append(event)

        for stage, events in sorted(stages.items()):
            if len(events) < self.rules.minimum_events:
                continue
            metrics = aggregator.summarize_stage(events)
            if metrics.failure_rate > self.rules.failure_rate:
                alerts.append({
                    "rule": "stage_failure_rate", "stage": stage,
                    "rate": metrics.failure_rate, "samples": len(events),
                })
            if stage.startswith("api.") and metrics.duration_p95_ms > self.rules.api_p95_ms:
                alerts.append({
                    "rule": "api_p95_latency", "stage": stage,
                    "p95_ms": metrics.duration_p95_ms, "samples": len(events),
                })
        return alerts


def main() -> int:
    """
    - Load rules and evaluate the configured databases.
    - Distinguish active alerts from an inability to evaluate them.
    """
    parser = argparse.ArgumentParser(description="Evaluate local operational alerts.")
    parser.add_argument("--database", type=Path, default=Path(
        os.environ.get("FEEDBACK_DB_PATH", "feedback-runtime.sqlite3"),
    ))
    parser.add_argument("--telemetry", type=Path, default=Path(
        os.environ.get("FEEDBACK_TELEMETRY_DB", "telemetry.sqlite3"),
    ))
    parser.add_argument("--rules", type=Path, default=Path(__file__).with_name("alerts.json"))
    args = parser.parse_args()
    try:
        rules = AlertRules.model_validate_json(args.rules.read_text(encoding="utf-8"))
        alerts = AlertChecker(args.database, args.telemetry, rules).check()
    except (OSError, ValueError, TypeError, sqlite3.Error) as error:
        print(json.dumps({"status": "check_failed", "error": str(error)}))
        return 2
    print(json.dumps({"status": "alert" if alerts else "clear", "alerts": alerts}, indent=2))
    return 1 if alerts else 0


if __name__ == "__main__":
    raise SystemExit(main())
