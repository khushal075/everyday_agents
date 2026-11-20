"""
Verify recovery After a process claims a job exists abruptly.
"""

import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from production.store import FeedbackStore, LeaseLost

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO_ROOT / "production" / "01_workflow_runtime" / "migrations"


# This child process commits a claim, reports its token and exits before running
# The agent or saving the outcome.

CRASHING_WORKER = """
import json
import os
from production.store import FeedbackStore

store = FeedbackStore(os.environ["FEEDBACK_DB_PATH"])
claim = store.claim_next(lease_seconds=2.0)
if claim is None:
    raise RuntimeError("Expected a queued job.")
print(json.dumps({
        "job_id": claim.job.job_id,
        "token": claim.token,
        "attempt": claim.attempt,
    }),
    flush=True
)
os._exit(17)
"""

class CrashRecoveryScenario:
    """
    Run a crash and recovery against an isolated SQLite database.
    """

    def run(self) -> None:
        """
        Check recovery, stale ownership rejection and the review count.
        """
        with TemporaryDirectory(prefix="feedback-recovery-") as directory:
            database_path = Path(directory) / "feedback.sqlite3"
            self._initialize(database_path)
            store = FeedbackStore(database_path)
            job_id = store.enqueue("This is terrible")
            environment = {
                **os.environ,
                "FEEDBACK_DB_PATH": str(database_path),
            }

            crashed = subprocess.run(
                [sys.executable, "-c", CRASHING_WORKER],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=10
            )

            if crashed.returncode != 17:
                raise AssertionError(
                    f"Expected injected crash, got {crashed.returncode}.\n"
                    f"{crashed.stdout}\n{crashed.stderr}"
                )

            claim = json.loads(crashed.stdout)
            assert claim["job_id"] == job_id
            assert claim["attempt"] == 1

            job = store.get_job(job_id)
            assert job is not None and job.status == 'running'
            assert store.get_review(job_id) is None
            print("PASS | Crashed process left the claimed job running.", flush=True)

            self._wait_for_expiry(database_path, job_id)

            # The expired owner's attempt to save an outcome must fail,
            # Even before another worker reclaims the job.
            try:
                store.complete(
                    job_id=job_id,
                    action="prepare_review",
                    reason="Late result from the old worker.",
                    claim_token=claim["token"],
                )
            except LeaseLost as error:
                print("PASS | Expired claim was rejected.", flush=True)
            else:
                raise AssertionError("An expired claim saved an outcome.")

            subprocess.run(
                [sys.executable, "-m", "production.worker"],
                cwd=REPO_ROOT,
                env=environment,
                check=True,
                timeout=30
            )

            job = store.get_job(job_id)
            review = store.get_review(job_id)

            assert job is not None and job.status == 'completed'
            assert job.action == 'prepare_review'
            assert review is not None and review.status == 'pending_review'

            with closing(sqlite3.connect(str(database_path))) as connection:
                attempt_count = connection.execute(
                    """
                        SELECT attempt_count FROM feedback_jobs WHERE job_id = ?
                    """, (job_id,)
                ).fetchone()[0]

                review_count = connection.execute(
                    """
                    SELECT COUNT(*) FROM review_records WHERE job_id = ?
                    """, (job_id,)
                ).fetchone()[0]

                assert attempt_count == 2, attempt_count
                assert review_count == 1, review_count

                print("PASS | Attempt 2 completed with exactly once pending review.", flush=True)


    def _initialize(self, database_path: Path) -> None:
        """
        Apply both migrations to a fresh database.
        """
        with closing(sqlite3.connect(str(database_path))) as connection:
            for filename in (
                "001_initial.sql", "002_worker_leases.sql", "003_retry_scheduling.sql",
                "004_access_and_approvals.sql", "005_cancellation_and_approval_controls.sql",
            ):
                connection.executescript(
                    (MIGRATIONS / filename).read_text(encoding="utf-8")
                )

    def _wait_for_expiry(self, database_path: Path, job_id: str) -> None:
        """
        Observe lease expiry using SQLite's clock, with a bounded wait.
        """
        deadline = time.monotonic() + 10.0

        with closing(sqlite3.connect(str(database_path))) as connection:
            while time.monotonic() < deadline:
                expired = connection.execute(
                    """
                        SELECT
                            lease_expires_at <= (julianday('now') - 2440587.5) * 86400
                        FROM
                            feedback_jobs
                        WHERE
                            job_id = ?
                    """, (job_id,)
                ).fetchone()[0]

                if expired:
                    return
                time.sleep(0.1)
        raise TimeoutError("The worker lease didn't expire in time.")


def main():
    """
    Run the crash recovery exercise
    """
    CrashRecoveryScenario().run()


if __name__ == "__main__":
    main()
