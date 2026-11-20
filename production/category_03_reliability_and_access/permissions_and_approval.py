"""Verify tenant access, durable approval, cancellation, and bounded retries."""

import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from production.api import FeedbackAPI
from production.category_03_reliability_and_access.approvals import (
    ApprovalPolicy, ApprovalRequired, ApprovalStore,
)
from production.category_03_reliability_and_access.security import AccessPolicy, Principal
from production.store import FeedbackStore, LeaseLost
from production.worker import FeedbackWorker

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO_ROOT / "production/01_workflow_runtime/migrations"
PERMISSIONS = frozenset({"submit_feedback", "read_job", "approve_action", "cancel_job"})
CREDENTIALS = {
    "tenant-a-key": Principal("operator-a", "tenant-a", PERMISSIONS),
    "tenant-b-key": Principal("operator-b", "tenant-b", PERMISSIONS),
    "reader-key": Principal("reader", "tenant-a", frozenset({"read_job"})),
}


class TimeoutPredictor:
    """Inject a retryable inference failure before any tool effect."""

    def predict(self, feedback: str):
        raise TimeoutError("Injected inference timeout.")


class PermissionsAndApprovalScenario:
    """Exercise the actual API and worker with isolated persistent state."""

    def _worker(self, database: Path) -> None:
        """Start a fresh worker process using the same database."""
        subprocess.run(
            [sys.executable, "-m", "production.worker"],
            cwd=REPO_ROOT,
            env={**os.environ, "FEEDBACK_DB_PATH": str(database)},
            check=True,
            timeout=30,
        )

    def _submit(self, client: TestClient) -> str:
        response = client.post("/feedback", json={"text": "This is terrible"})
        assert response.status_code == 202, response.text
        return response.json()["job_id"]

    def run(self) -> None:
        """Verify access, approval persistence, and recovery controls."""
        with TemporaryDirectory(prefix="feedback-access-") as directory:
            database = Path(directory) / "feedback.sqlite3"
            with closing(sqlite3.connect(database)) as connection:
                for migration in sorted(MIGRATIONS.glob("*.sql")):
                    connection.executescript(migration.read_text(encoding="utf-8"))

            store = FeedbackStore(database)
            headers = {"X-API-Key": "tenant-a-key"}
            app = FeedbackAPI(database, credentials=CREDENTIALS).app
            with TestClient(app, headers=headers) as client:
                job_id = self._submit(client)
                assert client.get(f"/jobs/{job_id}", headers={"X-API-Key": "bad"}).status_code == 401
                assert client.get(f"/jobs/{job_id}", headers={"X-API-Key": "tenant-b-key"}).status_code == 404
                assert client.post("/feedback", json={"text": "Hello"}, headers={"X-API-Key": "reader-key"}).status_code == 403
                self._worker(database)
                detail = client.get(f"/jobs/{job_id}").json()
                assert detail["job"]["status"] == "awaiting_approval", detail
                assert detail["review"] is None
                assert detail["proposal"]["action"] == "prepare_review"
                assert client.post(f"/jobs/{job_id}/approval", json={"approved": True}, headers={"X-API-Key": "reader-key"}).status_code == 403
                assert client.post(f"/jobs/{job_id}/approval", json={"approved": True}, headers={"X-API-Key": "tenant-b-key"}).status_code == 404
                assert client.post(f"/jobs/{job_id}/approval", json={"approved": True}).status_code == 200

            # Recreate the API and launch another worker after approval is saved.
            with TestClient(
                FeedbackAPI(database, credentials=CREDENTIALS).app, headers=headers,
            ) as client:
                self._worker(database)
                detail = client.get(f"/jobs/{job_id}").json()
                assert detail["job"]["status"] == "completed", detail
                assert detail["review"]["status"] == "pending_review"
                assert client.post(f"/jobs/{job_id}/approval", json={"approved": False}).status_code == 409
                print("PASS | Tenant access and approval across process restarts.")

                rejected_id = self._submit(client)
                self._worker(database)
                assert client.post(f"/jobs/{rejected_id}/approval", json={"approved": False}).status_code == 200
                assert store.get_job(rejected_id, "tenant-a").status == "failed"
                assert store.get_review(rejected_id, "tenant-a") is None
                print("PASS | Rejected actions create no review.")

                changed_id = self._submit(client)
                self._worker(database)
                assert client.post(f"/jobs/{changed_id}/approval", json={"approved": True}).status_code == 200
                approvals = ApprovalStore(database)
                approval = approvals.get_decision(f"{changed_id}:review", "tenant-a")
                assert approval is not None
                changed = replace(approval.request, parameters_json='{"feedback":"Changed"}')
                try:
                    approvals.save_decision(replace(approval, request=changed))
                except ApprovalRequired:
                    pass
                else:
                    raise AssertionError("Changed approval was accepted.")
                try:
                    ApprovalPolicy(AccessPolicy()).require(changed, approval)
                except ApprovalRequired:
                    pass
                else:
                    raise AssertionError("Changed parameters passed approval.")
                # Inject changed execution inputs to verify the worker also blocks them.
                with closing(sqlite3.connect(database)) as connection:
                    connection.execute(
                        "UPDATE feedback_jobs SET feedback_text = ? WHERE job_id = ?",
                        ("This is excellent", changed_id),
                    )
                    connection.commit()
                assert FeedbackWorker(store).run_once() == 1
                assert store.get_job(changed_id, "tenant-a").status == "failed"
                assert store.get_review(changed_id, "tenant-a") is None
                print("PASS | Changed action details are blocked.")

                cancelled_id = self._submit(client)
                claim = store.claim_next()
                assert claim is not None and claim.job.job_id == cancelled_id
                assert client.post(f"/jobs/{cancelled_id}/cancel").status_code == 200
                for operation in (
                    lambda: store.complete(cancelled_id, "prepare_review", "Late", claim_token=claim.token),
                    lambda: store.schedule_retry(claim, "Late", 0),
                    lambda: store.await_approval(claim, "prepare_review", "Late"),
                ):
                    try:
                        operation()
                    except LeaseLost:
                        pass
                    else:
                        raise AssertionError("Cancelled claim changed job state.")
                assert store.get_job(cancelled_id, "tenant-a").cancellation_requested
                assert store.get_review(cancelled_id, "tenant-a") is None

                waiting_id = self._submit(client)
                self._worker(database)
                assert client.post(f"/jobs/{waiting_id}/cancel").status_code == 200
                assert client.post(f"/jobs/{waiting_id}/approval", json={"approved": True}).status_code == 409

                queued_id = self._submit(client)
                assert client.post(f"/jobs/{queued_id}/cancel").status_code == 200
                assert store.claim_next() is None
                print("PASS | Cancellation blocks queued, running, and waiting work.")

            retry_id = store.enqueue("Retry this")
            worker = FeedbackWorker(store)
            worker.agent.predictor = TimeoutPredictor()
            for attempt in (1, 2):
                assert worker.run_once() == 1
                assert store.claim_next() is None
                with closing(sqlite3.connect(database)) as connection:
                    count, remaining = connection.execute(
                        """
                        SELECT attempt_count,
                            retry_at - (julianday('now') - 2440587.5) * 86400.0
                        FROM feedback_jobs WHERE job_id = ?
                        """, (retry_id,),
                    ).fetchone()
                    assert count == attempt and 0 < remaining <= 2 ** (attempt - 1)
                    # Advance this isolated fixture without sleeping through backoff.
                    connection.execute(
                        "UPDATE feedback_jobs SET retry_at = 0 WHERE job_id = ?", (retry_id,),
                    )
                    connection.commit()
            assert worker.run_once() == 1
            assert store.get_job(retry_id).status == "failed"
            assert store.get_job(retry_id).reason.startswith("Escalated:")
            assert store.get_review(retry_id) is None

            denied_id = store.enqueue("This is terrible")
            assert FeedbackWorker(store, tool_permissions=frozenset()).run_once() == 1
            assert store.get_review(denied_id) is None
            print("PASS | Retry limits, backoff, and worker tool permissions.")

            with closing(sqlite3.connect(database)) as connection:
                assert not connection.execute("PRAGMA foreign_key_check").fetchall()
                assert connection.execute(
                    "SELECT COUNT(*) FROM review_records WHERE job_id = ?", (job_id,),
                ).fetchone()[0] == 1
            print("PASS | Exactly one approved review and valid foreign keys.")


def main() -> None:
    """Run all Category 03 access and approval checks."""
    PermissionsAndApprovalScenario().run()


if __name__ == "__main__":
    main()
