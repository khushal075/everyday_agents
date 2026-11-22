"""
Run policy routing through the API, persistent store, and separate worker processes.

- Submit a tenant-owned job into an isolated migrated SQLite database.
- Retrieve evidence and prepare a proposal in a worker subprocess.
- Approve or reject the exact saved proposal through the API.
- Start another worker and verify the durable result and correlated telemetry.
- Use an explicit fixture generator by default; select Ollama for real inference.

The API uses FastAPI's in-process HTTP test client. Worker execution uses real
subprocesses. Temporary databases are removed after verification.
"""

import argparse
import io
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from fastapi.testclient import TestClient

from production.api import FeedbackAPI
from production.category_03_reliability_and_access.security import Principal
from production.category_04_evaluation_and_observability.metrics import MetricsAggregator
from production.category_04_evaluation_and_observability.telemetry import Telemetry
from production.category_05_deployment_and_operations.migrate import MigrationRunner

POLICY_PATH = Path(__file__).resolve().parent / "fixtures" / "support_policy.md"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FEEDBACK = "I was charged twice for my subscription."


class IntegratedFeedbackScenario:
    """
    - Exercise the actual API and persistent worker without touching user data.
    - Verify that approval resumes the saved proposal without further inference.
    """

    def __init__(self, *, generator: Literal["fixture", "ollama"] = "fixture", model: str = "", policy_path: Path = POLICY_PATH) -> None:
        """
        - Store explicit inference and policy settings for the exercise.

        :param generator: Reproducible fixture or actual Ollama inference.
        :param model: Installed model name required for Ollama mode.
        :param policy_path: Support policy available to the first worker.
        """
        if generator not in ("fixture", "ollama"):
            raise ValueError("Generator must be fixture or ollama.")
        if generator == "ollama" and not model.strip():
            raise ValueError("Ollama mode requires --model with an installed model name.")
        self.generator, self.model, self.policy_path = generator, model, policy_path.resolve()

    def run_worker(self, environment: dict[str, str]) -> None:
        """
        - Process one eligible job in a separate Python process.
        - Surface worker failures instead of claiming an end-to-end success.

        :param environment: Database, telemetry, and inference configuration.
        :return: None.
        """
        result = subprocess.run(
            [sys.executable, "-m", "production.worker"], cwd=REPO_ROOT,
            env=environment, capture_output=True, text=True, timeout=45,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Worker failed:\n{result.stdout}{result.stderr}")

    def run(self, feedback: str = DEFAULT_FEEDBACK, *, approved: bool = True) -> dict:
        """
        - Submit, prepare, decide approval, resume, and verify one feedback job.
        - Verify no review on rejection or missing policy evidence.

        :param feedback: Original customer text for the isolated example.
        :param approved: Whether the demonstration operator approves the proposal.
        :return: Verified outcome, persistent record, and stage names.
        """
        if not feedback.strip():
            raise ValueError("Feedback must not be blank.")
        permissions = frozenset({"submit_feedback", "read_job", "approve_action"})
        with TemporaryDirectory(prefix="integrated-feedback-") as directory:
            database = Path(directory) / "workflow.sqlite3"
            events = Path(directory) / "events.sqlite3"
            with redirect_stdout(io.StringIO()):
                MigrationRunner(database).run()
            telemetry = Telemetry(stream=io.StringIO(), database_path=events)
            environment = {
                **os.environ, "FEEDBACK_DB_PATH": str(database),
                "FEEDBACK_TELEMETRY_DB": str(events),
                "FEEDBACK_ROUTING_GENERATOR": self.generator,
                "FEEDBACK_ROUTING_MODEL": self.model,
                "FEEDBACK_POLICY_PATH": str(self.policy_path),
            }
            api = FeedbackAPI(database, credentials={
                "example-key": Principal("example-operator", "example-tenant", permissions),
            }, workflow_mode="policy", telemetry=telemetry)
            with TestClient(api.app, headers={"X-API-Key": "example-key"}) as client:
                submitted = client.post("/feedback", json={"text": feedback})
                if submitted.status_code != 202:
                    raise RuntimeError(submitted.text)
                job_id = submitted.json()["job_id"]
                self.run_worker(environment)
                details = client.get(f"/jobs/{job_id}").json()
                proposal = details["proposal"]
                if details["job"]["status"] == "awaiting_approval":
                    if details["review"] is not None or proposal is None:
                        raise RuntimeError("A waiting job must have a proposal and no review.")
                    decision = client.post(f"/jobs/{job_id}/approval", json={"approved": approved})
                    if decision.status_code != 200:
                        raise RuntimeError(decision.text)
                    # Prove resume uses stored evidence even without a working model or policy file.
                    environment.update(FEEDBACK_ROUTING_GENERATOR="unavailable", FEEDBACK_POLICY_PATH="/missing/policy.md")
                    self.run_worker(environment)
                    details = client.get(f"/jobs/{job_id}").json()
                    if details["proposal"] != proposal:
                        raise RuntimeError("Saved proposal changed during approval resume.")
                    expected_status = "completed" if approved else "failed"
                    if details["job"]["status"] != expected_status:
                        raise RuntimeError("Unexpected approval outcome.")
                    if approved:
                        parameters = json.loads(proposal["parameters_json"])
                        review = details["review"]
                        if review is None or any(review[key] != parameters[key] for key in ("route", "source", "heading", "reason")):
                            raise RuntimeError("Review differs from the approved proposal.")
                        if review["operation_id"] != proposal["operation_id"]:
                            raise RuntimeError("Review operation differs from the proposal.")
                    outcome = "review_created" if approved else "rejected"
                elif details["job"]["status"] == "completed" and details["job"]["action"] == "record" and proposal is None:
                    outcome = "no_policy_match"
                else:
                    raise RuntimeError(f"Unexpected prepared job status: {details['job']['status']}")
                # Running again must not create another review or repeat inference.
                self.run_worker(environment)
            with closing(sqlite3.connect(database)) as connection:
                count = connection.execute("SELECT COUNT(*) FROM review_records WHERE job_id=?", (job_id,)).fetchone()[0]
                if count != (1 if outcome == "review_created" else 0):
                    raise RuntimeError("Unexpected number of persistent reviews.")
                if connection.execute("PRAGMA foreign_key_check").fetchall():
                    raise RuntimeError("Foreign-key verification failed.")
            traces = [event for event in MetricsAggregator(events).read_events() if event.job_id == job_id]
            if not traces or any(event.run_id != job_id or event.tenant_id != "example-tenant" for event in traces):
                raise RuntimeError("Telemetry correlation differs from the saved job.")
            stages = [event.stage for event in traces]
            if outcome == "review_created" and not {"worker.proposal_restored", "worker.verification", "worker.completed"}.issubset(stages):
                raise RuntimeError("Missing resume or verification telemetry.")
            result = {"generator": self.generator, "outcome": outcome, "job": details["job"],
                      "proposal": proposal, "review": details["review"], "review_count": count,
                      "trace_run_id": job_id, "stages": stages}
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return result


def main() -> int:
    """
    - Select fixture or Ollama mode and run the isolated complete workflow.

    :return: Zero on verified success, one on workflow failure.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", default=DEFAULT_FEEDBACK)
    parser.add_argument("--generator", choices=("fixture", "ollama"), default="fixture")
    parser.add_argument("--model", default="")
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    parser.add_argument("--reject", action="store_true")
    args = parser.parse_args()
    try:
        IntegratedFeedbackScenario(generator=args.generator, model=args.model, policy_path=args.policy).run(args.text, approved=not args.reject)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, sqlite3.Error) as error:
        print(f"Integrated workflow failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
