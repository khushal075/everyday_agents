"""
Store feedback jobs and review records in SQLite.
"""
import math
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional
from time import perf_counter
from uuid import uuid4
from production.category_04_evaluation_and_observability.telemetry import EventOutcome, Telemetry

if TYPE_CHECKING:
    from production.category_03_reliability_and_access.approvals import ActionRequest

WorkflowMode = Literal["sentiment", "policy"]

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
    workflow_mode: WorkflowMode = "sentiment"


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
    operation_id: str | None = None
    route: str | None = None
    source: str | None = None
    heading: str | None = None
    reason: str | None = None

class LeaseLost(ValueError):
    """The worker's claim expired or another worker owns the job."""


def feedback_job(row: sqlite3.Row) -> FeedbackJob:
    """Read the public job fields from a database row."""
    values = {field.name: row[field.name] for field in fields(FeedbackJob) if field.name in row.keys()}
    values["approval_required"] = bool(values["approval_required"])
    values["cancellation_requested"] = bool(values["cancellation_requested"])
    return FeedbackJob(**values)


class FeedbackStore:
    """
    Give the api and worker access to the same SQLite database.
    """
    def __init__(
        self, database_path: str | Path, *, telemetry: Telemetry | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.telemetry = telemetry if telemetry is not None else Telemetry.from_environment()

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
        workflow_mode: WorkflowMode = "sentiment",
    ) -> str:
        """
        Save feedback as queued job and return its ID

        :param feedback_text:
        :return:
        """
        started = perf_counter()
        if not feedback_text.strip():
            raise ValueError("Feedback text must not be blank")

        if not tenant_id.strip():
            raise ValueError("tenant_id must not be blank.")
        if workflow_mode not in ("sentiment", "policy"):
            raise ValueError("workflow_mode must be sentiment or policy.")
        job_id = uuid4().hex
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO
                    feedback_jobs(job_id, feedback_text, tenant_id, approval_required, workflow_mode)
                VALUES
                    (?, ?, ?, ?, ?)
                """, (job_id, feedback_text, tenant_id, approval_required, workflow_mode)
            )
        self._event("store.queued", job_id, started)
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
        started = perf_counter()
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
            exhausted = connection.execute(
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
                RETURNING job_id
                """,
                (max_attempts, now),
            ).fetchall()

            previous = connection.execute(
                """
                SELECT status FROM feedback_jobs
                WHERE cancellation_requested = 0 AND attempt_count < ?
                  AND (
                      (status = 'queued' AND retry_at <= ?)
                      OR (status = 'running' AND lease_expires_at <= ?)
                  )
                ORDER BY created_at, job_id LIMIT 1
                """,
                (max_attempts, now, now),
            ).fetchone()
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

        for exhausted_job in exhausted:
            self._event("store.escalated", exhausted_job["job_id"], started, outcome="failed")
        if not rows:
            return None

        row = rows[0]
        self._event("store.claimed", row["job_id"], started, attempt=row["attempt_count"])
        if previous is not None and previous["status"] == "running":
            self._event("store.reclaimed", row["job_id"], started, attempt=row["attempt_count"])
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
        started = perf_counter()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._owned_job(connection, job_id, claim_token)
            if row["workflow_mode"] == "policy" and action == "prepare_review":
                raise ValueError("Policy reviews require complete_policy and a saved proposal.")
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
        self._event("store.completed", job_id, started)

    def save_policy_request(self, claim: JobClaim, request: "ActionRequest") -> bool:
        """
        - Save the exact routing proposal while the caller owns the lease.
        - Release the claim atomically when human approval is required.

        :param claim: Current worker claim.
        :param request: Validated policy action including its evidence snapshot.
        :return: True when execution must wait for human approval.
        """
        from production.feedback_workflow import FeedbackWorkflow
        from production.category_03_reliability_and_access.approvals import ApprovalStore
        started = perf_counter()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._owned_job(connection, claim.job.job_id, claim.token)
            if row["workflow_mode"] != "policy":
                raise ValueError("Cannot save a policy proposal for a sentiment job.")
            plan = FeedbackWorkflow.restore(
                request, feedback=row["feedback_text"], job_id=row["job_id"], tenant_id=row["tenant_id"],
            )
            ApprovalStore.write_request(connection, row["job_id"], request)
            approval = ApprovalStore.read_decision(connection, request.operation_id, request.tenant_id)
            waiting = bool(row["approval_required"]) and approval is None
            if waiting:
                connection.execute(
                    """UPDATE feedback_jobs SET status = 'awaiting_approval', action = 'prepare_review',
                        reason = ?, claim_token = NULL, lease_expires_at = NULL,
                        attempt_count = attempt_count - 1, updated_at = CURRENT_TIMESTAMP
                        WHERE job_id = ?""",
                    (plan.recommendation.reason, row["job_id"]),
                )
        self._event("store.awaiting_approval" if waiting else "store.proposal_saved", claim.job.job_id, started)
        return waiting

    def complete_policy(self, claim: JobClaim, request: "ActionRequest") -> None:
        """
        - Commit one review and job completion under a valid, uncancelled lease.
        - Recheck the saved proposal and exact approval inside the transaction.
        - Keep route and citation metadata with the persistent review.

        :param claim: Current worker claim.
        :param request: Exact previously persisted policy proposal.
        :return: None.
        """
        from production.feedback_workflow import FeedbackWorkflow
        from production.category_03_reliability_and_access.approvals import (
            ActionRequest, ApprovalPolicy, ApprovalRequired, ApprovalStore,
        )
        from production.category_03_reliability_and_access.security import AccessPolicy
        started = perf_counter()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._owned_job(connection, claim.job.job_id, claim.token)
            if row["workflow_mode"] != "policy":
                raise ValueError("Policy execution requires a policy job.")
            plan = FeedbackWorkflow.restore(
                request, feedback=row["feedback_text"], job_id=row["job_id"], tenant_id=row["tenant_id"],
            )
            saved = connection.execute(
                "SELECT * FROM action_requests WHERE operation_id = ? AND job_id = ? AND tenant_id = ?",
                (request.operation_id, row["job_id"], row["tenant_id"]),
            ).fetchone()
            if saved is None or request != ActionRequest(
                saved["operation_id"], saved["tenant_id"], saved["action"], saved["parameters_json"],
            ):
                raise ApprovalRequired("Execution requires the exact saved proposal.")
            if row["approval_required"]:
                ApprovalPolicy(AccessPolicy()).require(request, ApprovalStore.read_decision(
                    connection, request.operation_id, request.tenant_id,
                ))
            recommendation = plan.recommendation
            connection.execute(
                """INSERT INTO review_records(job_id, operation_id, route, source, heading, reason)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (row["job_id"], request.operation_id, recommendation.route,
                 recommendation.policy_passage.source, recommendation.policy_passage.heading,
                 recommendation.reason),
            )
            connection.execute(
                """UPDATE feedback_jobs SET status = 'completed', action = 'prepare_review',
                   reason = ?, error = NULL, claim_token = NULL, lease_expires_at = NULL,
                   updated_at = CURRENT_TIMESTAMP WHERE job_id = ?""",
                (recommendation.reason, row["job_id"]),
            )
        self._event("store.completed", claim.job.job_id, started)

    def schedule_retry(
        self, claim: JobClaim, error: str, delay_seconds: float,
    ) -> None:
        """Release an owned job and persist its next eligible time."""
        started = perf_counter()
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
        self._event("store.retry_scheduled", claim.job.job_id, started)

    def fail(
        self, job_id: str, error: str, *, claim_token: str,
        reason: str | None = None,
    ) -> None:
        """
        Mark a running job as failed and save the error.
        """
        started = perf_counter()
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
        self._event("store.failed", job_id, started, outcome="failed")

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
        started = perf_counter()
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
        self._event("store.awaiting_approval", claim.job.job_id, started)

    def cancel(self, job_id: str, tenant_id: str) -> bool:
        """Cancel pending work and revoke any current worker claim."""
        started = perf_counter()
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
        if result.rowcount == 1:
            self._event("store.cancelled", job_id, started)
        return result.rowcount == 1

    def _event(
        self, stage: str, job_id: str, started: float, *,
        attempt: int | None = None, outcome: EventOutcome = "passed",
    ) -> None:
        """
        - Emit a committed state transition with job correlation fields.
        - Read metadata after the business transaction has closed.
        - Preserve the business result if telemetry metadata cannot be read.
        """
        duration_ms = (perf_counter() - started) * 1000
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT tenant_id, attempt_count FROM feedback_jobs WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
        except sqlite3.Error:
            return
        if row is not None:
            self.telemetry.safe_emit(
                run_id=job_id, job_id=job_id, tenant_id=row["tenant_id"],
                stage=stage, outcome=outcome, duration_ms=duration_ms,
                attempt=attempt if attempt is not None else max(1, row["attempt_count"]),
            )
