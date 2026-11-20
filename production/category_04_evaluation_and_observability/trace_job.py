"""
    - Follow a persistent feedback job through approval and completion.
    - Run the API through its test client and workers in separate processes.
    - Emit correlation events at the boundaries observed by this exercise.
"""

import os
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager, closing
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import uuid4
from typing import Optional

from fastapi.testclient import TestClient
from production.api import FeedbackAPI

from production.category_03_reliability_and_access.security import Principal
from production.category_04_evaluation_and_observability.telemetry import Telemetry


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO_ROOT / "production/01_workflow_runtime/migrations"

class JobTraceScenario:
    """
        - Trace one feedback job across API requests and worker processes.
        - Verify each observed state before reporting a successful stage.
    """
    def __init__(self, telemetry: Telemetry) -> None:
        """
            - Store the event emitter.
            - Assign an ID shared by all events in this exercise.
        """
        self.telemetry = telemetry
        self.run_id = uuid4().hex
        self.job_id : Optional[str] = None

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """
            - Measure one observed stage.
            - Emit a passed event or an error event.
            - Propagate exceptions so the exercise fails visibility.
        """
        started = perf_counter()
        outcome = 'passed'
        error_type = None

        try:
            yield
        except Exception as error:
            outcome = "error"
            error_type = type(error).__name__
            raise
        finally:
            self.telemetry.emit(
                run_id=self.run_id,
                job_id=self.job_id,
                team_id="trace-tenant",
                stage=name,
                outcome=outcome,
                duration_ms=(perf_counter() - started) * 1000,
                error_type=error_type,
            )

    def run_worker(self, database: Path) -> None:
        """
            - Start a fresh worker process using the exercise database.
            - Capture its output so JSON events remain easy to collect.
            - fail is the worker exits unsuccessfully.
        """
        result = subprocess.run(
            [sys.executable, "-m", "production.worker"],
            cwd=REPO_ROOT,
            env={**os.environ, "FEEDBACK_DB_PATH": str(database)},
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            raise RuntimeError(result.stdout + result.stderr)


    def run(self) -> None:
        """
            - Initialize a isolated database and authenticated API.
            - Submit feedback, inspect the proposal and approve it.
            - Verify completion after a second worker process starts.
        """
        credentials = {
            "trace-key": Principal(
                "trace-operator",
                "trace-tenant",
                frozenset({"submit_feedback", "read_job", "approve_action"})
            )
        }

        with TemporaryDirectory(prefix="feedback-trace-") as directory:
            database = Path(directory) / "feedback.sqlite3"
            with closing(sqlite3.connect(database)) as connection:
                for migration in sorted(MIGRATIONS.glob("*.sql")):
                    connection.executescript(
                        migration.read_text(encoding="utf-8")
                    )

            api = FeedbackAPI(database, credentials=credentials)

            with TestClient(
                    api.app,
                    headers={"X-API-Key": "trace-key"},
            ) as client:
                with self.stage("feedback.submitted"):
                    response = client.post(
                        "/feedback",
                        json={"text": "This is terrible"},
                    )
                    assert response.status_code == 202, response.text
                    self.job_id = response.json()["job_id"]

                with self.stage("worker.awaiting_approval"):
                    self.run_worker(database)
                    response = client.get(f"/jobs/{self.job_id}")
                    assert response.status_code == 200, response.text
                    detail = response.json()
                    assert detail["job"]["status"] == "awaiting_approval"
                    assert detail["proposal"]["action"] == "prepare_review"
                    assert detail["review"] is None

                with self.stage("approval.saved"):
                    response = client.post(
                        f"/jobs/{self.job_id}/approval",
                        json={"approved": True},
                    )
                    assert response.status_code == 200, response.text

                with self.stage("worker.completed"):
                    self.run_worker(database)
                    response = client.get(f"/jobs/{self.job_id}")
                    assert response.status_code == 200, response.text
                    detail = response.json()
                    assert detail["job"]["status"] == "completed"
                    assert detail["review"]["status"] == "pending_review"

            print(f"PASS | Job {self.job_id} approved and completed.")
            print(f"Trace run ID: {self.run_id}")

def main():
    """
        - Create the structured event emitter.
        - Run the job tracing exercise.
    """
    JobTraceScenario(Telemetry()).run()

if __name__ == "__main__":
    main()
