"""Expose tenant-scoped feedback, approval, and cancellation endpoints."""

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from production.category_03_reliability_and_access.approvals import (
    ActionRequest, ApprovalPolicy, ApprovalRequired, ApprovalStore,
)
from production.category_03_reliability_and_access.security import (
    AccessDenied, AccessPolicy, AuthenticationFailed, CredentialResolver, Principal,
)
from production.store import FeedbackJob, FeedbackStore, ReviewRecord


class FeedbackRequest(BaseModel):
    """Feedback submitted by an authenticated caller."""

    text: str


class QueuedJob(BaseModel):
    """The identifier of newly saved work."""

    job_id: str
    status: Literal["queued"] = "queued"


class JobDetails(BaseModel):
    """A tenant-owned job, its review, and any proposed action."""

    job: FeedbackJob
    review: ReviewRecord | None = None
    proposal: ActionRequest | None = None


class ApprovalDecisionRequest(BaseModel):
    """A human decision for the saved proposal shown by the API."""

    approved: bool


class FeedbackAPI:
    """Register endpoints using trusted, server-configured caller identities."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        credentials: Mapping[str, Principal] | None = None,
        require_approval: bool = True,
    ) -> None:
        self.store = FeedbackStore(database_path)
        self.approvals = ApprovalStore(database_path)
        self.access = AccessPolicy()
        self.approval_policy = ApprovalPolicy(self.access)
        self.credentials = CredentialResolver(credentials or {})
        self.require_approval = require_approval
        self.app = FastAPI(title="Everyday Agents Feedback API")
        self.app.add_api_route(
            "/feedback", self.submit_feedback, methods=["POST"], status_code=202,
        )
        self.app.add_api_route("/jobs/{job_id}", self.get_job, methods=["GET"])
        self.app.add_api_route(
            "/jobs/{job_id}/approval", self.decide_approval, methods=["POST"],
        )
        self.app.add_api_route(
            "/jobs/{job_id}/cancel", self.cancel_job, methods=["POST"],
        )

    def _principal(self, api_key: str | None, permission: str) -> Principal:
        """Authenticate and check the requested permission."""
        try:
            principal = self.credentials.authenticate(api_key)
            self.access.require(
                principal, resource_tenant_id=principal.tenant_id, permission=permission,
            )
            return principal
        except AuthenticationFailed as error:
            raise HTTPException(401, str(error)) from error
        except AccessDenied as error:
            raise HTTPException(403, str(error)) from error

    def _job(self, job_id: str, principal: Principal) -> FeedbackJob:
        """Load a job only within the caller's tenant."""
        job = self.store.get_job(job_id, principal.tenant_id)
        if job is None:
            raise HTTPException(404, "Feedback job not found.")
        return job

    def submit_feedback(
        self, request: FeedbackRequest, x_api_key: str | None = Header(default=None),
    ) -> QueuedJob:
        """Save feedback with the tenant derived from the credential."""
        principal = self._principal(x_api_key, "submit_feedback")
        if not request.text.strip():
            raise HTTPException(400, "Feedback text must not be blank.")
        job_id = self.store.enqueue(
            request.text, tenant_id=principal.tenant_id,
            approval_required=self.require_approval,
        )
        return QueuedJob(job_id=job_id)

    def get_job(
        self, job_id: str, x_api_key: str | None = Header(default=None),
    ) -> JobDetails:
        """Return tenant-owned state and the exact proposed action."""
        principal = self._principal(x_api_key, "read_job")
        job = self._job(job_id, principal)
        review = self.store.get_review(job_id, principal.tenant_id)
        proposal = self.approvals.get_request(f"{job_id}:review", principal.tenant_id)
        return JobDetails(job=job, review=review, proposal=proposal)

    def decide_approval(
        self, job_id: str, request: ApprovalDecisionRequest,
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, str]:
        """Save a decision for the immutable proposal and release waiting work."""
        principal = self._principal(x_api_key, "approve_action")
        self._job(job_id, principal)
        proposal = self.approvals.get_request(f"{job_id}:review", principal.tenant_id)
        if proposal is None:
            raise HTTPException(409, "No action proposal exists for this job.")
        try:
            decision = self.approval_policy.decide(
                principal, proposal, approved=request.approved,
            )
            self.approvals.save_decision(decision)
        except ApprovalRequired as error:
            raise HTTPException(409, str(error)) from error
        return {"job_id": job_id, "decision": decision.decision}

    def cancel_job(
        self, job_id: str, x_api_key: str | None = Header(default=None),
    ) -> dict[str, str]:
        """Cancel pending work and revoke its worker claim."""
        principal = self._principal(x_api_key, "cancel_job")
        self._job(job_id, principal)
        if not self.store.cancel(job_id, principal.tenant_id):
            raise HTTPException(409, "The job is already terminal.")
        return {"job_id": job_id, "status": "cancelled"}


def configured_credentials() -> dict[str, Principal]:
    """Load API key mappings from the server environment."""
    entries = json.loads(os.environ.get("FEEDBACK_CREDENTIALS", "{}"))
    return {
        key: Principal(
            subject_id=value["subject_id"],
            tenant_id=value["tenant_id"],
            permissions=frozenset(value["permissions"]),
        )
        for key, value in entries.items()
    }


app = FeedbackAPI(
    os.environ.get("FEEDBACK_DB_PATH", "feedback-runtime.sqlite3"),
    credentials=configured_credentials(),
).app
