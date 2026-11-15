"""
Claim and process one feedback job from the SQLite queue.
"""

import os
import sys
from pathlib import Path
from everyday_agents.agents.sentiment.agent import create_agent
from production.store import FeedbackStore


class FeedbackWorker:
    """
    Run the sentiment agent for a queued job and save the outcome.
    """
    def __init__(self, store: FeedbackStore):
        self.store = store
        self.agent = create_agent()

    def run_once(self) -> int:
        job = self.store.claim_next()
        if job is None:
            print("No queued jobs.")
            return 0

        print(f"Claimed job {job.job_id}")

        try:
            run = self.agent.run(job.feedback_text)
        except Exception as error:
            return self._fail_job(
                job_id=job.job_id,
                error=f"{type(error).__name__}: {error}",
            )

        if not run.result.success:
            return self._fail_job(
                job_id=job.job_id,
                error= run.result.error or "The sentiment agent failed.",
            )

        action = run.decision.action
        if action not in ("record", "prepare_review"):
            return self._fail_job(
                job_id=job.job_id,
                error=f"Unsupported action: {action!r}.",
            )

        # The store commits the item and any review written together.
        self.store.complete(
            job_id=job.job_id,
            action=action,
            reason=run.decision.reason,
        )

        print(f"Completed job {job.job_id} with action {action}")
        return 0

    def _fail_job(self, job_id: str, error: str) -> int:
        """
        Save the failure and return a nonzero exit code.
        """
        self.store.fail(job_id=job_id, error=error)
        print(f"Failed job {job_id} with error {error}")
        return 1


def main() -> int:
    """
    Connect to the same database as the feedback API
    """
    database_path = Path(
        os.environ.get("FEEDBACK_DB_PATH", "feedback-runtime.sqlite3")
    )
    return FeedbackWorker(FeedbackStore(database_path)).run_once()

if __name__ == "__main__":
    raise SystemExit(main())
