"""
Store feedback jobs and review records in SQLite.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

JobStatus = Literal["queued", "running", "completed", "failed"]
FeedbackAction = Literal["record", "prepare_review"]


@dataclass(frozen=True)
class FeedbackJob:
    """
    A saved feedback request and its current processing outcome.
    """
    job_id: str
    feedback_text: str
    status: JobStatus
    action: FeedbackAction | None
    reason: str | None
    error: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ReviewRecord:
    """
    A review item created for the completed feedback job.
    """
    job_id: str
    status: Literal["pending_review"]
    created_at: str

class FeedbackStore:
    """
    Give the api and worker access to the same SQLite database.
    """
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """
        Open a connection and commit or rollback its transaction.
        :return:
        """
        connection = sqlite3.connect(self.database_path, timeout=0.5)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            with connection:
                yield connection
        finally:
            connection.close()


    def enqueue(self, feedback_text: str) -> str:
        """
        Save feedback as queued job and return its ID

        :param feedback_text:
        :return:
        """
        if not feedback_text.strip():
            raise ValueError("Feedback text must not be blank")

        job_id = uuid4().hex
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO
                    feedback_jobs(job_id, feedback_text)
                VALUES
                    (?, ?)
                """, (job_id, feedback_text)
            )
        return job_id

    def get_job(self, job_id: str) -> Optional[FeedbackJob]:
        """
        Look up a job by ID
        """
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT
                    *
                FROM
                    feedback_jobs
                WHERE
                    job_id = ?
                """, (job_id,),
            ).fetchone()

        return FeedbackJob(**dict(row)) if row is not None else None

    def get_review(self, job_id: str) -> Optional[ReviewRecord]:
        """
        Look up review item associated with a job.
        """
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT
                    *
                FROM
                    review_records
                WHERE
                    job_id = ?
                """, (job_id,),
            ).fetchone()
        return ReviewRecord(**dict(row)) if row is not None else None

    def claim_next(self) -> Optional[FeedbackJob]:
        """
        Move the oldest queued job to running and return it.

        :return:
        """
        with self._connection() as connection:
            # Select and claim the job in one statement so two workers
            # Cannot claim the same queued job.
            row = connection.execute(
                """
                UPDATE
                    feedback_jobs
                SET
                    status = 'running', updated_at = CURRENT_TIMESTAMP
                WHERE
                    job_id = (
                        SELECT
                            job_id
                        FROM
                            feedback_jobs
                        WHERE
                            status = 'queued'
                        ORDER BY
                            created_at, job_id
                        LIMIT 1
                    )
                    RETURNING *
                """
            ).fetchone()
        return FeedbackJob(**dict(row)) if row is not None else None

    def complete(
            self,
            job_id: str,
            action: FeedbackAction,
            reason: str
    ) -> None:
        """
        Save the decision and any review item in one transaction.
        """
        with self._connection() as connection:
            result = connection.execute(
                """
                UPDATE
                    feedback_jobs
                SET
                    status = 'completed',
                    action = ?,
                    reason = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE
                    job_id = ? AND status = 'running'
                """, (action, reason, job_id)
            )
            if result.rowcount == 0:
                raise ValueError(f"JOB: {job_id} is missing or no longer running")

            if action == "prepare_review":
                connection.execute(
                    """
                    INSERT INTO
                        review_records (job_id)
                    VALUES
                        (?)
                    """, (job_id,)
                )

    def fail(self, job_id: str, error: str) -> None:
        """
        Mark a running job as failed and save the error.
        """
        with self._connection() as connection:
            result = connection.execute(
                """
                UPDATE
                    feedback_jobs
                SET
                    status = 'failed',
                    error = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE
                    job_id = ? AND status = 'running'
                """, (error, job_id),
            )

            if result.rowcount == 0:
                raise ValueError(f"JOB: {job_id} is missing or no longer running")
