"""
Bind an approval to an exact action and its serialization parameters.
"""
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Mapping, Optional
from uuid import uuid4

from production.category_03_reliability_and_access.security import AccessPolicy, Principal
from pathlib import Path

ActionValue = str | int | float | bool | None


@dataclass(frozen=True)
class ActionRequest:
    """
    An immutable snapshot of a proposed action.
    """
    operation_id: str
    tenant_id: str
    action: str
    parameters_json: str

    @classmethod
    def create(
        cls,
        *,
        operation_id: str,
        tenant_id: str,
        action: str,
        parameters: Mapping[str, ActionValue],
    ) -> "ActionRequest":

        """
        Serialize simple named parameters into a stable representations.
        """
        if not operation_id.strip() or not tenant_id.strip() or not action.strip():
            raise ValueError("Operation, tenant, and action are required.")

        for name, value in parameters.items():
            if not isinstance(name, str):
                raise ValueError("Parameter name must be a string.")

            if value is not None and type(value) not in (str, int, float, bool):
                raise ValueError("Parameter value must be JSON scaler value.")

        return cls(
            operation_id=operation_id,
            tenant_id=tenant_id,
            action=action,
            parameters_json=json.dumps(
                dict(parameters),
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        )

@dataclass(frozen=True)
class ApprovalRecord:
    """
    An approver's decision for the next action request.
    """
    approval_id: str
    request: ActionRequest
    decision: Literal["approved", "rejected"]
    approved_by: str
    decided_at: str


class ApprovalRequired(PermissionError):
    """
    Execution requires approval for the current action required.
    """


class ApprovalPolicy:
    """
    Check approver access and validate approval before execution.
    """
    def __init__(self, access_policy: AccessPolicy) -> None:
        self.access_policy = access_policy

    def decide(
        self,
        principal: Principal,
        request: ActionRequest,
        *,
        approved: bool,
    ) -> ApprovalRecord:
        """
        Create a decision after checking the caller's approval permission.
        """

        self.access_policy.require(
            principal=principal,
            resource_tenant_id=request.tenant_id,
            permission="approve_action",
        )

        return ApprovalRecord(
            approval_id=uuid4().hex,
            request=request,
            decision="approved" if approved else "rejected",
            approved_by=principal.subject_id,
            decided_at=datetime.now(timezone.utc).isoformat(),

        )

    def require(
        self,
        request: ActionRequest,
        approval: Optional[ApprovalRecord],
    ) -> None:
        """
        Allow execution only when approval matches the current request.
        """
        if approval is None:
            raise ApprovalRequired("Approval is required.")

        if approval.decision != "approved":
            raise ApprovalRequired("The action was rejected.")

        if approval.request != request:
            raise ApprovalRequired("The action details changed after approval.")

class ApprovalStore:
    """Persist immutable proposals and decisions in the workflow database."""

    def __init__(self, database_path: str | Path) -> None:
        from production.store import FeedbackStore
        self.store = FeedbackStore(database_path)

    @staticmethod
    def write_request(
        connection: sqlite3.Connection, job_id: str, request: ActionRequest,
    ) -> None:
        """Allow an identical repeat, rejecting changed operation details."""
        row = connection.execute(
            "SELECT * FROM action_requests WHERE operation_id = ?",
            (request.operation_id,),
        ).fetchone()
        if row is not None:
            saved = ActionRequest(
                row["operation_id"], row["tenant_id"], row["action"],
                row["parameters_json"],
            )
            if saved != request or row["job_id"] != job_id:
                raise ApprovalRequired("The saved action details differ.")
            return
        connection.execute(
            """
            INSERT INTO action_requests
                (operation_id, job_id, tenant_id, action, parameters_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (request.operation_id, job_id, request.tenant_id, request.action,
             request.parameters_json),
        )

    def save_request(self, job_id: str, request: ActionRequest) -> None:
        """Persist a proposal for a tenant-owned job."""
        with self.store._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.write_request(connection, job_id, request)

    def get_request(self, operation_id: str, tenant_id: str) -> ActionRequest | None:
        """Load a proposal within a tenant."""
        with self.store._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM action_requests
                WHERE operation_id = ? AND tenant_id = ?
                """,
                (operation_id, tenant_id),
            ).fetchone()
        if row is None:
            return None
        return ActionRequest(
            row["operation_id"], row["tenant_id"], row["action"], row["parameters_json"],
        )

    @staticmethod
    def read_decision(
        connection: sqlite3.Connection, operation_id: str, tenant_id: str,
    ) -> ApprovalRecord | None:
        """Load the immutable decision and the exact referenced proposal."""
        row = connection.execute(
            """
            SELECT a.*, r.action, r.parameters_json
            FROM approval_records AS a
            JOIN action_requests AS r
              ON r.operation_id = a.operation_id AND r.tenant_id = a.tenant_id
            WHERE a.operation_id = ? AND a.tenant_id = ?
            """,
            (operation_id, tenant_id),
        ).fetchone()
        if row is None:
            return None
        request = ActionRequest(
            row["operation_id"], row["tenant_id"], row["action"], row["parameters_json"],
        )
        return ApprovalRecord(
            row["approval_id"], request, row["decision"],
            row["approved_by"], row["decided_at"],
        )

    def get_decision(self, operation_id: str, tenant_id: str) -> ApprovalRecord | None:
        """Read a decision after reopening the database."""
        with self.store._connection() as connection:
            return self.read_decision(connection, operation_id, tenant_id)

    def save_decision(self, approval: ApprovalRecord) -> None:
        """Commit a decision and resume or reject its waiting job atomically."""
        request = approval.request
        with self.store._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT r.*, j.status, j.cancellation_requested
                FROM action_requests AS r
                JOIN feedback_jobs AS j
                  ON j.job_id = r.job_id AND j.tenant_id = r.tenant_id
                WHERE r.operation_id = ? AND r.tenant_id = ?
                """,
                (request.operation_id, request.tenant_id),
            ).fetchone()
            if row is None:
                raise ApprovalRequired("The proposal does not exist.")
            saved = ActionRequest(
                row["operation_id"], row["tenant_id"], row["action"], row["parameters_json"],
            )
            if saved != request:
                raise ApprovalRequired("The action details changed after approval.")
            previous = self.read_decision(connection, request.operation_id, request.tenant_id)
            if previous is not None:
                if previous == approval:
                    return
                raise ApprovalRequired("This operation already has a decision.")
            if row["status"] != "awaiting_approval" or row["cancellation_requested"]:
                raise ApprovalRequired("The job is no longer awaiting approval.")
            connection.execute(
                """
                INSERT INTO approval_records
                    (approval_id, operation_id, tenant_id, decision, approved_by, decided_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (approval.approval_id, request.operation_id, request.tenant_id,
                 approval.decision, approval.approved_by, approval.decided_at),
            )
            approved = approval.decision == "approved"
            connection.execute(
                """
                UPDATE feedback_jobs SET status = ?, error = ?, retry_at = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ? AND tenant_id = ?
                """,
                ("queued" if approved else "failed",
                 None if approved else "Action rejected by approver.",
                 row["job_id"], request.tenant_id),
            )
