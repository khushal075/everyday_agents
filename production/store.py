"""
Store feedback jobs and review records in SQLite.
"""
import math
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

JobStatus = Literal["queued", "running", "awaiting_approval", "completed", "failed"]
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
    tenant_id: str = "local"
    approval_required: bool = False
    cancellation_requested: bool = False


@dataclass(frozen=True)
class JobClaim:
    """
    The job and the claim issued to its worker.
    """
    job: FeedbackJob
    token: str
    attempt: int

@dataclass(frozen=True)
class ReviewRecord:
    """
    A review item created for the completed feedback job.
    """
    job_id: str
    status: Literal["pending_review"]
    created_at: str

class LeaseLost(ValueError):
    """The worker's claim expired or another worker owns the job."""


def feedback_job(row: sqlite3.Row) -> FeedbackJob:
    """Read the public job fields from a database row."""
    values = {field.name: row[field.name] for field in fields(FeedbackJob)}
    values["approval_required"] = bool(values["approval_required"])
    values["cancellation_requested"] = bool(values["cancellation_requested"])
    return FeedbackJob(**values)


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
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            with connection:
                yield connection
        finally:
            connection.close()


    def enqueue(
        self, feedback_text: str, *, tenant_id: str = "local",
        approval_required: bool = False,
    ) -> str:
        """
        Save feedback as queued job and return its ID

        :param feedback_text:
        :return:
        """
        if not feedback_text.strip():
            raise ValueError("Feedback text must not be blank")

        if not tenant_id.strip():
            raise ValueError("tenant_id must not be blank.")
        job_id = uuid4().hex
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO
                    feedback_jobs(job_id, feedback_text, tenant_id, approval_required)
                VALUES
                    (?, ?, ?, ?)
                """, (job_id, feedback_text, tenant_id, approval_required)
            )
        return job_id

    def get_job(self, job_id: str, tenant_id: str = "local") -> Optional[FeedbackJob]:
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
                    job_id = ? AND tenant_id = ?
                """, (job_id, tenant_id),
            ).fetchone()

        return feedback_job(row) if row is not None else None

    def get_review(self, job_id: str, tenant_id: str = "local") -> Optional[ReviewRecord]:
        """Look up a review through its tenant-owned job."""
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT r.* FROM review_records AS r
                JOIN feedback_jobs AS j ON j.job_id = r.job_id
                WHERE r.job_id = ? AND j.tenant_id = ?
                """,
                (job_id, tenant_id),
            ).fetchone()
        return ReviewRecord(**dict(row)) if row is not None else None

    def claim_next(
        self, lease_seconds: float = 30.0, *, max_attempts: int = 3,
    ) -> JobClaim | None:
        """Claim a queued job or reclaim a job whose lease expired."""
        if not math.isfinite(lease_seconds) or lease_seconds <= 0:
            raise ValueError("lease_seconds must be finite and positive.")

        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")

        token = uuid4().hex
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = connection.execute(
                "SELECT (julianday('now') - 2440587.5) * 86400.0"
            ).fetchone()[0]

            # Expired claims at the attempt limit require human review.
            connection.execute(
                """
                UPDATE feedback_jobs
                SET status = 'failed',
                    reason = 'Escalated: attempt limit reached.',
                    error = COALESCE(error, 'Worker lease expired.'),
                    claim_token = NULL,
                    lease_expires_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE cancellation_requested = 0 AND attempt_count >= ?
                  AND (
                      status = 'queued'
                      OR (status = 'running' AND lease_expires_at <= ?)
                  )
                """,
                (max_attempts, now),
            )

            rows = connection.execute(
                """
                UPDATE feedback_jobs
                SET status = 'running',
                    claim_token = ?,
                    lease_expires_at = ?,
                    attempt_count = attempt_count + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = (
                    SELECT job_id
                    FROM feedback_jobs
                    WHERE cancellation_requested = 0 AND attempt_count < ?
                      AND (
                          (status = 'queued' AND retry_at <= ?)
                          OR (status = 'running' AND lease_expires_at <= ?)
                      )
                    ORDER BY created_at, job_id
                    LIMIT 1
                )
                RETURNING *
                """,
                (token, now + lease_seconds, max_attempts, now, now),
            ).fetchall()

        if not rows:
            return None

        row = rows[0]
        return JobClaim(
            job=feedback_job(row),
            token=token,
            attempt=row["attempt_count"],
        )

    def complete(
            self,
            job_id: str,
            action: FeedbackAction,
            reason: str,
            *,
            claim_token: str,
    ) -> None:
        """
        Save the decision and any review item in one transaction.
        """
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._owned_job(connection, job_id, claim_token)
            proposal_exists = connection.execute(
                "SELECT 1 FROM action_requests WHERE operation_id = ? AND tenant_id = ?",
                (f"{job_id}:review", row["tenant_id"]),
            ).fetchone() is not None
            if row["approval_required"] and (action == "prepare_review" or proposal_exists):
                from production.category_03_reliability_and_access.approvals import (
                    ActionRequest, ApprovalPolicy, ApprovalStore,
                )
                from production.category_03_reliability_and_access.security import AccessPolicy

                request = ActionRequest.create(
                    operation_id=f"{job_id}:review",
                    tenant_id=row["tenant_id"],
                    action=action,
                    parameters={"feedback": row["feedback_text"], "reason": reason},
                )
                approval = ApprovalStore.read_decision(
                    connection, request.operation_id, request.tenant_id,
                )
                ApprovalPolicy(AccessPolicy()).require(request, approval)
            result = connection.execute(
                """
                UPDATE
                    feedback_jobs
                SET
                    status = 'completed',
                    action = ?,
                    reason = ?,
                    error = NULL,
                    claim_token = NULL,
                    lease_expires_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE
                    job_id = ? AND status = 'running'
                  AND cancellation_requested = 0
                    AND claim_token = ?
                    AND lease_expires_at >
                        (julianday('now') - 2440587.5) * 86400.0
                """, (action, reason, job_id, claim_token)
            )
            if result.rowcount != 1:
                raise LeaseLost("The worker no longer owns this job.")

            if action == "prepare_review":
                connection.execute(
                    """
                    INSERT INTO
                        review_records (job_id)
                    VALUES
                        (?)
                    """, (job_id,)
                )

    def schedule_retry(
        self, claim: JobClaim, error: str, delay_seconds: float,
    ) -> None:
        """Release an owned job and persist its next eligible time."""
        if not math.isfinite(delay_seconds) or delay_seconds < 0:
            raise ValueError("delay_seconds must be finite and nonnegative.")

        with self._connection() as connection:
            result = connection.execute(
                """
                UPDATE feedback_jobs
                SET status = 'queued',
                    error = ?,
                    retry_at = (julianday('now') - 2440587.5) * 86400.0 + ?,
                    claim_token = NULL,
                    lease_expires_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                  AND status = 'running'
                  AND cancellation_requested = 0
                  AND claim_token = ?
                  AND lease_expires_at >
                      (julianday('now') - 2440587.5) * 86400.0
                """,
                (error, delay_seconds, claim.job.job_id, claim.token),
            )
            if result.rowcount != 1:
                raise LeaseLost("The worker no longer owns this job.")

    def fail(
        self, job_id: str, error: str, *, claim_token: str,
        reason: str | None = None,
    ) -> None:
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
                    reason = ?,
                    claim_token = NULL,
                    lease_expires_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE
                    job_id = ? AND status = 'running'
                  AND cancellation_requested = 0
                    AND claim_token = ?
                    AND lease_expires_at >
                        (julianday('now') - 2440587.5) * 86400.0
                """, (error, reason, job_id, claim_token),
            )

            if result.rowcount != 1:
                raise LeaseLost("The worker no longer owns this job.")

    def _owned_job(
        self, connection: sqlite3.Connection, job_id: str, token: str,
    ) -> sqlite3.Row:
        """Read a valid owned job while holding the write transaction."""
        row = connection.execute(
            """
            SELECT * FROM feedback_jobs
            WHERE job_id = ? AND status = 'running'
              AND cancellation_requested = 0 AND claim_token = ?
              AND lease_expires_at >
                  (julianday('now') - 2440587.5) * 86400.0
            """,
            (job_id, token),
        ).fetchone()
        if row is None:
            raise LeaseLost("The worker no longer owns this job.")
        return row

    def await_approval(self, claim: JobClaim, action: str, reason: str) -> None:
        """Save a proposal and release the lease in the same transaction."""
        from production.category_03_reliability_and_access.approvals import (
            ActionRequest, ApprovalStore,
        )
        request = ActionRequest.create(
            operation_id=f"{claim.job.job_id}:review",
            tenant_id=claim.job.tenant_id,
            action=action,
            parameters={"feedback": claim.job.feedback_text, "reason": reason},
        )
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._owned_job(connection, claim.job.job_id, claim.token)
            ApprovalStore.write_request(connection, claim.job.job_id, request)
            connection.execute(
                """
                UPDATE feedback_jobs
                SET status = 'awaiting_approval', action = ?, reason = ?,
                    claim_token = NULL, lease_expires_at = NULL,
                    attempt_count = attempt_count - 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                """,
                (action, reason, claim.job.job_id),
            )

    def cancel(self, job_id: str, tenant_id: str) -> bool:
        """Cancel pending work and revoke any current worker claim."""
        with self._connection() as connection:
            result = connection.execute(
                """
                UPDATE feedback_jobs
                SET cancellation_requested = 1, status = 'failed',
                    error = 'Cancellation requested.', reason = 'Cancelled by caller.',
                    claim_token = NULL, lease_expires_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ? AND tenant_id = ?
                  AND status IN ('queued', 'running', 'awaiting_approval')
                """,
                (job_id, tenant_id),
            )
        return result.rowcount == 1
