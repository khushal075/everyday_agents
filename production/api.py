"""
Accept feedback and expose the status of saved job over HTTP
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

from production.store import FeedbackJob, FeedbackStore, ReviewRecord

class FeedbackRequest(BaseModel):
    """
    The feedback text supplied by the caller.
    """
    text: str

class QueuedJob(BaseModel):
    """
    The response returned once feedback has been saved.
    """
    job_id: str
    status: Literal["queued"]  = "queued"

class JobDetails(BaseModel):
    """
        - The current job status
        - Its review items
        when present
    """
    job: FeedbackJob
    review: Optional[ReviewRecord]

class FeedbackAPI:
    """
    Register HTTP endpoints backend by the SQLite feedback store.
    """
    def __init__(self, database_path: str | Path) -> None:
        self.store = FeedbackStore(database_path)
        self.app = FastAPI(title="Everyday Agent Feedback API")

        self.app.add_api_route(
            "/feedback",
            self.submit_feedback,
            methods=["POST"],
            status_code=status.HTTP_202_ACCEPTED,
        )

        self.app.add_api_route(
            "/jobs/{job_id}",
            self.get_job,
            methods=["GET"],
        )

    def submit_feedback(self, request: FeedbackRequest) -> QueuedJob:
        """
        Save feedback and return the ID the caller can use to track it.

        :param request:
        :return:
        """
        if not request.text.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Feedback text must not being blank",
            )

        job_id = self.store.enqueue(request.text)
        return QueuedJob(job_id=job_id)

    def get_job(self, job_id: str) -> JobDetails:
        """
        Return the current job state and any review item.
        """
        job = self.store.get_job(job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Feedback Job not found"
            )

        review = None
        if job.status == "completed" and job.action == "prepare_review":
            review = self.store.get_review(job_id)

        return JobDetails(job=job, review=review)


app = FeedbackAPI(
    os.environ.get("FEEDBACK_DB_PATH", "feedback-runtime.sqlite3")
).app
