"""
- Submit negative feedback through the deployed authenticated HTTP API.
- Approve its exact saved proposal and wait for worker completion.
- Verify the final review item and report the created job ID.
"""

import argparse
import json
import math
import os
import time
from urllib.request import Request, urlopen


class SmokeTest:
    """
    - Exercise the deployed API and long-running worker together.
    - Bound each wait and fail when a job enters an unexpected state.
    """

    def __init__(self, url: str, api_key: str, timeout: float, bearer_token: str = "") -> None:
        """
        - Configure the API address, credential, and wait timeout.
        """
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.bearer_token = bearer_token
        self.timeout = timeout

    def request(self, path: str, body: dict | None = None) -> dict:
        """
        - Send an authenticated JSON request.
        - Use POST when a body is supplied, otherwise use GET.
        """
        headers = {"Content-Type": "application/json"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        else:
            headers["X-API-Key"] = self.api_key
        request = Request(
            self.url + path,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers=headers,
        )
        with urlopen(request, timeout=min(5, self.timeout)) as response:
            return json.load(response)

    def wait_for(self, job_id: str, expected: str) -> dict:
        """
        - Poll the job endpoint until the requested state is observed.
        - Fail on terminal failure or expiry of the wait deadline.
        """
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            detail = self.request(f"/jobs/{job_id}")
            state = detail["job"]["status"]
            if state == expected:
                return detail
            if state in {"failed", "completed"}:
                raise ValueError(f"Expected {expected}, observed {state} for job {job_id}.")
            time.sleep(0.1)
        raise TimeoutError(f"Job {job_id} did not reach {expected}.")

    def run(self) -> str:
        """
        - Submit feedback, inspect its proposal, and approve it.
        - Confirm the job and review contain the submitted request.
        """
        text = "This is terrible. I was charged twice for my subscription."
        queued = self.request("/feedback", {"text": text})
        job_id = queued["job_id"]
        waiting = self.wait_for(job_id, "awaiting_approval")
        proposal = waiting["proposal"]
        if waiting["review"] is not None or proposal["action"] != "prepare_review":
            raise ValueError("Unexpected approval proposal.")
        parameters = json.loads(proposal["parameters_json"])
        if parameters["feedback"] != text:
            raise ValueError("Proposal feedback differs from the submitted text.")
        self.request(f"/jobs/{job_id}/approval", {"approved": True})
        completed = self.wait_for(job_id, "completed")
        if (
            completed["job"]["feedback_text"] != text
            or completed["job"]["action"] != "prepare_review"
            or completed["review"]["job_id"] != job_id
            or completed["review"]["status"] != "pending_review"
        ):
            raise ValueError("Completed review differs from the expected outcome.")
        if completed["job"]["workflow_mode"] == "policy":
            review = completed["review"]
            if any(review[key] != parameters[key] for key in ("route", "source", "heading", "reason")):
                raise ValueError("Persistent review differs from the approved policy proposal.")
            if review["operation_id"] != proposal["operation_id"]:
                raise ValueError("Review operation differs from the approved proposal.")
        return job_id


def main() -> int:
    """
    - Read the credential from the environment.
    - Return a nonzero exit code when the deployed workflow fails.
    """
    parser = argparse.ArgumentParser(description="Check the deployed feedback workflow.")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    key = os.environ.get("FEEDBACK_API_KEY", "")
    bearer = os.environ.get("FEEDBACK_BEARER_TOKEN", "")
    if bool(key) == bool(bearer) or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("Set exactly one API key or bearer token and a positive finite timeout.")
    try:
        job_id = SmokeTest(args.url, key, args.timeout, bearer).run()
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"Smoke test failed: {error}")
        return 1
    print(f"PASS | Deployed job {job_id} approved and completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
