"""Verify portable identity and notification adapters against local HTTP fixtures."""

import io
import json
import os
import socket
import subprocess
import sys
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from production.api import FeedbackAPI
from production.category_03_reliability_and_access.oidc import OIDCAuthenticator
from production.category_03_reliability_and_access.security import Principal
from production.category_04_evaluation_and_observability.telemetry import Telemetry
from production.category_05_deployment_and_operations.migrate import MigrationRunner
from production.category_05_deployment_and_operations.check_alerts import main as check_alerts_main
from production.category_05_deployment_and_operations.smoke_test import SmokeTest
from production.category_05_deployment_and_operations.notifications import DeliveryFailed, WebhookNotifier


class FixtureHandler(BaseHTTPRequestHandler):
    """Serve public keys and capture webhook deliveries for deterministic tests."""

    def log_message(self, *args):
        """Keep fixture logs out of test output."""

    def do_GET(self):
        """Return the configured JWKS or an injected service error."""
        if self.path != "/jwks":
            self.send_error(404)
            return
        self.send_response(self.server.key_status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"keys": self.server.keys}).encode())

    def do_POST(self):
        """Record an alert payload and respond with the next configured status."""
        payload = self.rfile.read(int(self.headers["Content-Length"]))
        self.server.deliveries.append((
            {name.lower(): value for name, value in self.headers.items()}, json.loads(payload)
        ))
        status = self.server.statuses.pop(0) if self.server.statuses else 204
        if status == 0:
            self.connection.shutdown(2)
            self.connection.close()
            self.close_connection = True
            return
        self.send_response(status)
        if status == 302:
            self.send_header("Location", self.server.url + "/redirected")
        self.end_headers()


class ExternalIntegrationsTests(unittest.TestCase):
    """Exercise actual key fetching and notification HTTP calls on loopback."""

    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        cls.server.url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.database = self.root / "workflow.sqlite3"
        with redirect_stdout(io.StringIO()):
            MigrationRunner(self.database).run()
        key = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        key.update({"kid": "fixture-key", "use": "sig", "alg": "RS256"})
        self.server.keys = [key]
        self.server.key_status = 200
        self.server.statuses = []
        self.server.deliveries = []
        self.oidc = OIDCAuthenticator(
            self.server.url, "feedback-api", self.server.url + "/jwks",
            allow_local_http=True,
        )
        self.output = io.StringIO()
        self.telemetry = Telemetry(stream=self.output)
        self.api = FeedbackAPI(
            self.database, oidc=self.oidc, telemetry=self.telemetry,
            credentials={"fallback": Principal("local", "tenant-a", frozenset({"read_job"}))},
        )

    def tearDown(self):
        self.directory.cleanup()

    def token(self, **changes):
        claims = {
            "iss": self.server.url, "aud": "feedback-api", "sub": "operator",
            "iat": int(time.time()), "exp": int(time.time()) + 120,
            "tenant_id": "tenant-a",
            "scope": "submit_feedback read_job approve_action cancel_job",
        }
        claims.update(changes)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "fixture-key"})

    def notifier(self):
        return WebhookNotifier(
            self.server.url + "/alerts", self.root / "notifications.sqlite3",
            token="fixture-webhook-secret", allow_local_http=True,
        )

    def test_valid_bearer_scopes_tenant_and_telemetry(self):
        token = self.token()
        with TestClient(self.api.app) as client:
            response = client.post("/feedback", json={"text": "This is terrible"}, headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(response.status_code, 202, response.text)
            job_id = response.json()["job_id"]
            detail = client.get(f"/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["job"]["tenant_id"], "tenant-a")
            other = self.token(tenant_id="tenant-b")
            self.assertEqual(client.get(f"/jobs/{job_id}", headers={"Authorization": f"Bearer {other}"}).status_code, 404)
        self.assertNotIn(token, self.output.getvalue())

    def test_missing_permissions_are_forbidden(self):
        with TestClient(self.api.app) as client:
            response = client.post("/feedback", json={"text": "Feedback"}, headers={"Authorization": f"Bearer {self.token(scope='read_job')}"})
            self.assertEqual(response.status_code, 403)

    def test_bad_signature_expiry_issuer_and_audience_are_rejected(self):
        claims = jwt.decode(self.token(), options={"verify_signature": False})
        forged = jwt.encode(claims, self.wrong_key, algorithm="RS256", headers={"kid": "fixture-key"})
        tokens = [
            forged, self.token(exp=int(time.time()) - 30),
            self.token(iss="https://wrong.example"), self.token(aud="wrong-api"),
            self.token(tenant_id=None), self.token(iat=int(time.time()) + 1000),
        ]
        with TestClient(self.api.app) as client:
            for token in tokens:
                with self.subTest(token_type=tokens.index(token)):
                    response = client.post("/feedback", json={"text": "Feedback"}, headers={"Authorization": f"Bearer {token}"})
                    self.assertEqual(response.status_code, 401, response.text)

    def test_missing_required_claim_and_wrong_algorithm_are_rejected(self):
        claims = jwt.decode(self.token(), options={"verify_signature": False})
        claims.pop("exp")
        missing = jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "fixture-key"})
        wrong = jwt.encode(claims, "a-long-test-only-symmetric-secret-key", algorithm="HS256")
        with TestClient(self.api.app) as client:
            for token in (missing, wrong):
                self.assertEqual(client.get("/jobs/missing", headers={"Authorization": f"Bearer {token}"}).status_code, 401)

    def test_key_service_failure_is_unavailable_and_mixed_credentials_fail(self):
        self.server.key_status = 503
        with TestClient(self.api.app) as client:
            response = client.get("/jobs/missing", headers={"Authorization": f"Bearer {self.token()}"})
            self.assertEqual(response.status_code, 503)
            response = client.get("/jobs/missing", headers={"Authorization": "Bearer invalid", "X-API-Key": "fallback"})
            self.assertEqual(response.status_code, 401)

    def test_nonlocal_http_requires_https(self):
        with self.assertRaises(ValueError):
            OIDCAuthenticator("http://provider.example", "api", "http://provider.example/jwks", allow_local_http=True)
        with self.assertRaises(ValueError):
            WebhookNotifier("http://receiver.example", self.root / "notifications.sqlite3", allow_local_http=True)

    def test_transient_webhook_failure_reuses_delivery_and_payload(self):
        self.server.statuses = [503, 204]
        notifier = self.notifier()
        alerts = [{"rule": "old_queued_jobs", "jobs": 1}]
        self.assertEqual(notifier.deliver(alerts, "incident-1"), "incident-1")
        self.assertEqual(len(self.server.deliveries), 2)
        first_headers, first_body = self.server.deliveries[0]
        second_headers, second_body = self.server.deliveries[1]
        self.assertEqual(first_headers["idempotency-key"], "incident-1")
        self.assertEqual(first_headers["authorization"], "Bearer fixture-webhook-secret")
        self.assertEqual(first_body, second_body)
        self.assertEqual(second_headers["x-delivery-id"], "incident-1")
        # Reopening the notifier simulates the next checker process.
        self.notifier().deliver(alerts, "incident-1")
        self.assertEqual(len(self.server.deliveries), 2)
        with self.assertRaises(ValueError):
            notifier.deliver([{"rule": "different"}], "incident-1")

    def test_permanent_failure_and_redirect_are_not_retried(self):
        for status in (400, 302):
            with self.subTest(status=status):
                self.server.statuses = [status]
                before = len(self.server.deliveries)
                with self.assertRaises(DeliveryFailed):
                    self.notifier().deliver([{"rule": "test"}], f"permanent-{status}")
                self.assertEqual(len(self.server.deliveries), before + 1)

    def test_retry_budget_persists_across_notifier_instances(self):
        self.server.statuses = [503, 503, 503]
        alerts = [{"rule": "test"}]
        with self.assertRaises(DeliveryFailed):
            self.notifier().deliver(alerts, "exhausted")
        self.assertEqual(len(self.server.deliveries), 3)
        with self.assertRaises(DeliveryFailed):
            self.notifier().deliver(alerts, "exhausted")
        self.assertEqual(len(self.server.deliveries), 3)
        with closing(sqlite3.connect(self.root / "notifications.sqlite3")) as connection:
            self.assertEqual(connection.execute(
                "SELECT attempts,state FROM notification_deliveries WHERE delivery_id='exhausted'"
            ).fetchone(), (3, "failed"))

    def test_ambiguous_connection_drop_retries_with_same_identity(self):
        self.server.statuses = [0, 204]
        self.notifier().deliver([{"rule": "test"}], "connection-drop")
        self.assertEqual(len(self.server.deliveries), 2)
        self.assertEqual(self.server.deliveries[0][1], self.server.deliveries[1][1])
        self.assertEqual(
            self.server.deliveries[0][0]["idempotency-key"],
            self.server.deliveries[1][0]["idempotency-key"],
        )

    def test_alert_checker_delivers_only_when_opted_in(self):
        events = self.root / "events.sqlite3"
        Telemetry(stream=io.StringIO(), database_path=events)
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                "INSERT INTO feedback_jobs(job_id,feedback_text,created_at) VALUES (?,?,?)",
                ("old", "Feedback", "2000-01-01 00:00:00"),
            )
            connection.commit()
        arguments = [
            "check_alerts", "--database", str(self.database),
            "--telemetry", str(events),
        ]
        environment = {
            "FEEDBACK_ALERT_WEBHOOK_URL": self.server.url + "/alerts",
            "FEEDBACK_ALERT_ALLOW_LOCAL_HTTP": "1",
            "FEEDBACK_NOTIFICATIONS_DB": str(self.root / "notifications.sqlite3"),
        }
        with patch.dict("os.environ", environment):
            with patch("sys.argv", arguments), redirect_stdout(io.StringIO()):
                self.assertEqual(check_alerts_main(), 1)
            self.assertEqual(self.server.deliveries, [])
            with patch("sys.argv", arguments + ["--notify", "--delivery-id", "checker"]), redirect_stdout(io.StringIO()):
                self.assertEqual(check_alerts_main(), 1)
        self.assertEqual(len(self.server.deliveries), 1)
        self.assertEqual(self.server.deliveries[0][1]["delivery_id"], "checker")

    def test_bearer_smoke_through_real_api_and_worker_processes(self):
        from urllib.request import urlopen

        environment = {
            **os.environ,
            "FEEDBACK_DB_PATH": str(self.database),
            "FEEDBACK_TELEMETRY_DB": str(self.root / "process-events.sqlite3"),
            "FEEDBACK_WORKER_HEARTBEAT": str(self.root / "worker-heartbeat.json"),
            "FEEDBACK_CREDENTIALS": "{}",
            "FEEDBACK_OIDC_ISSUER": self.server.url,
            "FEEDBACK_OIDC_AUDIENCE": "feedback-api",
            "FEEDBACK_OIDC_JWKS_URL": self.server.url + "/jwks",
            "FEEDBACK_OIDC_TENANT_CLAIM": "tenant_id",
            "FEEDBACK_OIDC_PERMISSIONS_CLAIM": "scope",
            "FEEDBACK_OIDC_ALLOW_LOCAL_HTTP": "1",
        }
        processes = []
        with socket.socket() as listener, (self.root / "services.log").open("w+") as output:
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            url = f"http://127.0.0.1:{listener.getsockname()[1]}"
            try:
                processes.append(subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "production.api:app",
                     "--fd", str(listener.fileno()), "--log-level", "warning"],
                    env=environment, pass_fds=(listener.fileno(),),
                    stdout=output, stderr=subprocess.STDOUT,
                ))
                processes.append(subprocess.Popen(
                    [sys.executable, "-m", "production.category_05_deployment_and_operations.run_worker",
                     "--poll-seconds", "0.01"],
                    env=environment, stdout=output, stderr=subprocess.STDOUT,
                ))
                deadline = time.monotonic() + 10
                while True:
                    if any(process.poll() is not None for process in processes):
                        output.seek(0)
                        self.fail(output.read())
                    try:
                        with urlopen(url + "/openapi.json", timeout=0.5):
                            break
                    except OSError:
                        if time.monotonic() >= deadline:
                            self.fail("The API did not become ready.")
                        time.sleep(0.05)
                job_id = SmokeTest(url, "", 10, bearer_token=self.token()).run()
                with closing(sqlite3.connect(self.database)) as connection:
                    self.assertEqual(connection.execute(
                        "SELECT tenant_id,status FROM feedback_jobs WHERE job_id=?", (job_id,)
                    ).fetchone(), ("tenant-a", "completed"))
                    self.assertEqual(connection.execute(
                        "SELECT COUNT(*) FROM review_records WHERE job_id=?", (job_id,)
                    ).fetchone()[0], 1)
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.terminate()
                for process in processes:
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
