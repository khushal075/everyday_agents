"""
Verify that feedback queued while the worker is offline can finish later.
"""

import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from production.api import FeedbackAPI

MIGRATION = Path(__file__).resolve().parent / "migrations" / "001_initial.sql"
REPO_ROOT = Path(__file__).resolve().parents[2]

def main():
    """
    Submit Feedback through the API and process it in a separate worker.
    """
    with TemporaryDirectory(prefix="feedback-runtime-") as directory:
        database_path = Path(directory) / "feedback-runtime.db"

        with closing(sqlite3.connect(str(database_path))) as connection:
            connection.executescript(MIGRATION.read_text(encoding="utf-8"))

        with TestClient(FeedbackAPI(database_path).app) as client:
            submission = client.post("/feedback", json={"text": 'This is terrible'})

            assert submission.status_code == 202, submission.text
            job_id = submission.json()["job_id"]
            before = client.get(f"/jobs/{job_id}")
            assert before.status_code == 200, before.text
            queued  = before.json()
            assert queued["job"]["status"] == "queued", queued
            assert queued['review'] is None, queued
            print(f"Job {job_id} is queued while the worker is offline.", flush=True)

            # Start a fresh python process that opens the same SQLite file.
            subprocess.run(
                [sys.executable, "-m", "production.worker"],
                cwd=REPO_ROOT,
                env={**os.environ, "FEEDBACK_DB_PATH": str(database_path)},
                check=True,
                timeout=30
            )

            after = client.get(f"/jobs/{job_id}")
            assert after.status_code == 200, after.text
            completed = after.json()
            assert completed["job"]["status"] == "completed", completed
            assert completed['job']['action'] == 'prepare_review', completed
            assert completed['review'] is not None, completed
            assert completed['review']['job_id'] == job_id, completed
            assert completed['review']['status'] == 'pending_review', completed

        with closing(sqlite3.connect(str(database_path))) as connection:
            count = connection.execute(
                """
                    SELECT
                        COUNT(*)
                    FROM
                        review_records
                    WHERE
                        job_id = ?
                """, (job_id,)
            ).fetchone()[0]

            assert count == 1, f"Expected one review record, found {count}"

    print("PASS: The saved job completed with exactly one pending review.")


if __name__ == "__main__":
    main()
