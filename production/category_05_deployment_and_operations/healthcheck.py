"""
- Check API responsiveness and workflow database readability.
- Check heartbeat freshness and worker process existence.
- Return a nonzero exit code when the selected check fails.
"""

import argparse
import json
import math
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from time import time
from urllib.request import urlopen


def check_database(database_path: Path) -> None:
    """
    - Open the workflow database in read-only mode.
    - Verify that the current runtime tables and columns are available.
    """
    uri = database_path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
        connection.execute(
            """
            SELECT tenant_id, approval_required, cancellation_requested,
                   claim_token, lease_expires_at, retry_at
            FROM feedback_jobs LIMIT 1
            """
        ).fetchall()
        for table, column in (
            ("review_records", "job_id"),
            ("action_requests", "operation_id"),
            ("approval_records", "approval_id"),
        ):
            connection.execute(f"SELECT {column} FROM {table} LIMIT 1").fetchall()


def check_api(base_url: str) -> None:
    """
    - Read the API's public OpenAPI document.
    - Verify that all feedback control endpoints are registered.
    """
    with urlopen(base_url.rstrip("/") + "/openapi.json", timeout=5) as response:
        document = json.load(response)
    required = {
        "/feedback", "/jobs/{job_id}",
        "/jobs/{job_id}/approval", "/jobs/{job_id}/cancel",
    }
    if not isinstance(document, dict) or not required.issubset(document.get("paths", {})):
        raise ValueError("Expected feedback routes are missing.")


def check_worker(heartbeat_path: Path, max_age_seconds: float) -> None:
    """
    - Reject invalid, future-dated, or stale heartbeat timestamps.
    - Verify the heartbeat PID from the worker's own process namespace.
    """
    if not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be finite and positive.")
    heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    timestamp = heartbeat["timestamp"]
    pid = heartbeat["pid"]
    if type(timestamp) not in (int, float) or not math.isfinite(timestamp):
        raise ValueError("Invalid heartbeat timestamp.")
    if type(pid) is not int or pid < 1:
        raise ValueError("Invalid heartbeat process ID.")
    age = time() - timestamp
    if age < 0 or age > max_age_seconds:
        raise ValueError(f"Invalid heartbeat age: {age:.1f} seconds.")
    os.kill(pid, 0)


def main() -> int:
    """
    - Select API/database checks or the worker heartbeat check.
    - Print a short result and return the corresponding exit code.
    """
    parser = argparse.ArgumentParser(description="Check feedback service health.")
    parser.add_argument("service", choices=["api", "worker"])
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--database", type=Path, default=Path(
        os.environ.get("FEEDBACK_DB_PATH", "feedback-runtime.sqlite3"),
    ))
    parser.add_argument("--heartbeat", type=Path, default=Path(
        os.environ.get("FEEDBACK_WORKER_HEARTBEAT", "worker-heartbeat.json"),
    ))
    parser.add_argument("--max-age-seconds", type=float, default=60)
    args = parser.parse_args()
    try:
        if args.service == "api":
            check_database(args.database)
            check_api(args.url)
        else:
            check_worker(args.heartbeat, args.max_age_seconds)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        print(f"Unhealthy: {error}")
        return 1
    print(f"Healthy: {args.service}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
