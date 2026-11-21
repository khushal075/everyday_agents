"""
- Follow actual API, database, and worker events for an approved feedback job.
- Share a telemetry database with worker subprocesses.
- Verify the emitted lifecycle and its correlation fields.
"""

import argparse
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from production.api import FeedbackAPI
from production.category_03_reliability_and_access.security import Principal
from production.category_04_evaluation_and_observability.metrics import MetricsAggregator
from production.category_04_evaluation_and_observability.telemetry import Telemetry

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO_ROOT / "production/01_workflow_runtime/migrations"


class JobTraceScenario:
    """
    - Run the approval lifecycle with separate worker processes.
    - Read saved component events and verify their ordering.
    """

    def __init__(self, telemetry: Telemetry) -> None:
        """
        - Require persistent telemetry for cross-process verification.
        - Store the emitter shared with the API.
        """
        if telemetry.database_path is None:
            raise ValueError("The trace exercise requires a telemetry database.")
        self.telemetry = telemetry

    def run_worker(self, database: Path) -> None:
        """
        - Start a worker with the same event database as the API.
        - Propagate worker failure with its captured diagnostics.
        """
        result = subprocess.run(
            [sys.executable, "-m", "production.worker"],
            cwd=REPO_ROOT,
            env={
                **os.environ,
                "FEEDBACK_DB_PATH": str(database),
                "FEEDBACK_TELEMETRY_DB": str(self.telemetry.database_path.resolve()),
            },
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stdout + result.stderr)

    def run(self) -> None:
        """
        - Submit, approve, and complete one job in an isolated workflow database.
        - Verify stage presence, ordering, and consistent job correlation.
        """
        credentials = {
            "trace-key": Principal(
                "trace-operator", "trace-tenant",
                frozenset({"submit_feedback", "read_job", "approve_action"}),
            ),
        }
        with TemporaryDirectory(prefix="feedback-trace-") as directory:
            database = Path(directory) / "feedback.sqlite3"
            with closing(sqlite3.connect(database)) as connection:
                for migration in sorted(MIGRATIONS.glob("*.sql")):
                    connection.executescript(migration.read_text(encoding="utf-8"))

            api = FeedbackAPI(
                database, credentials=credentials, telemetry=self.telemetry,
            )
            with TestClient(api.app, headers={"X-API-Key": "trace-key"}) as client:
                response = client.post("/feedback", json={"text": "This is terrible"})
                assert response.status_code == 202, response.text
                job_id = response.json()["job_id"]

                self.run_worker(database)
                response = client.get(f"/jobs/{job_id}")
                assert response.status_code == 200, response.text
                assert response.json()["job"]["status"] == "awaiting_approval"
                assert response.json()["review"] is None

                response = client.post(
                    f"/jobs/{job_id}/approval", json={"approved": True},
                )
                assert response.status_code == 200, response.text
                self.run_worker(database)

                response = client.get(f"/jobs/{job_id}")
                assert response.status_code == 200, response.text
                assert response.json()["job"]["status"] == "completed"
                assert response.json()["review"]["status"] == "pending_review"

            events = [
                event for event in MetricsAggregator(self.telemetry.database_path).read_events()
                if event.job_id == job_id
            ]
            assert events
            assert all(event.run_id == job_id for event in events)
            assert all(event.tenant_id == "trace-tenant" for event in events)
            assert all(event.attempt >= 1 for event in events)
            stages = [event.stage for event in events]
            required = (
                "store.queued", "api.submit_feedback", "store.claimed",
                "worker.prediction", "worker.decision", "worker.permission",
                "store.awaiting_approval", "worker.awaiting_approval",
                "store.approved", "api.decide_approval", "worker.approval",
                "store.completed", "worker.execution", "worker.completed",
            )
            for stage in required:
                assert stage in stages, f"Missing component event: {stage}"
            assert stages.index("store.queued") < stages.index("store.claimed")
            assert stages.index("store.awaiting_approval") < stages.index("store.approved")
            assert stages.index("store.approved") < stages.index("store.completed")
            assert sum(stage == "worker.completed" for stage in stages) == 1
            print(f"PASS | Verified {len(events)} component events for job {job_id}.")
            print(f"Trace run ID: {job_id}")
            print(f"Telemetry database: {self.telemetry.database_path}")


def main() -> None:
    """
    - Accept a telemetry destination for this trace exercise.
    - Run and verify actual component events.
    """
    parser = argparse.ArgumentParser(description="Trace a persistent feedback job.")
    parser.add_argument("--database", type=Path, default=Path("telemetry.sqlite3"))
    args = parser.parse_args()
    JobTraceScenario(Telemetry(database_path=args.database)).run()


if __name__ == "__main__":
    main()
