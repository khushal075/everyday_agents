"""
- Verify policy routing across persistence, approval, leases, and worker restart.
- Exercise the real HTTP adapter against a local inference-protocol fixture.
- Keep every workflow database isolated from user data.
"""

import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import closing, redirect_stdout
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from production.api import FeedbackAPI
from production.category_02_models_retrieval_and_tools.context import ContextBuilder
from production.category_02_models_retrieval_and_tools.models import (
    InvalidModelResponse, ModelUnavailable, OllamaRoutingGenerator,
    RoutingModel, ScriptedRoutingGenerator, configured_routing_model,
)
from production.category_02_models_retrieval_and_tools.retrieval import PolicyRetriever
from production.category_02_models_retrieval_and_tools.tools import ToolRejected
from production.category_03_reliability_and_access.approvals import (
    ActionRequest, ApprovalPolicy, ApprovalRequired, ApprovalStore,
)
from production.category_03_reliability_and_access.security import AccessPolicy, Principal
from production.category_04_evaluation_and_observability.telemetry import Telemetry
from production.category_05_deployment_and_operations.migrate import MigrationRunner
from production.feedback_workflow import FeedbackWorkflow
from production.store import FeedbackStore, LeaseLost
from production.worker import FeedbackWorker

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / 'production/category_02_models_retrieval_and_tools/fixtures/support_policy.md'
FEEDBACK = 'I was charged twice for my subscription.'


class FeedbackWorkflowTests(unittest.TestCase):
    """Exercise the integrated workflow using temporary persistent databases."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = Path(self.directory.name) / 'feedback.sqlite3'
        with redirect_stdout(io.StringIO()):
            MigrationRunner(self.database).run()
        self.telemetry = Telemetry(stream=io.StringIO())
        self.store = FeedbackStore(self.database, telemetry=self.telemetry)
        self.approvals = ApprovalStore(self.database, telemetry=self.telemetry)
        self.operator = Principal('operator', 'tenant-a', frozenset({'approve_action'}))

    def tearDown(self):
        self.directory.cleanup()

    def workflow(self, generate=None, **kwargs):
        return FeedbackWorkflow(PolicyRetriever(POLICY), RoutingModel(generate or ScriptedRoutingGenerator()), **kwargs)

    def enqueue(self, text=FEEDBACK, approval=True):
        return self.store.enqueue(text, tenant_id='tenant-a', approval_required=approval, workflow_mode='policy')

    def run_worker(self, workflow=None, **kwargs):
        with redirect_stdout(io.StringIO()):
            return FeedbackWorker(self.store, workflow=workflow or self.workflow(), **kwargs).run_once()

    def request(self, job_id):
        return self.approvals.get_request(f'{job_id}:review', 'tenant-a')

    def approve(self, job_id, approved=True):
        approval = ApprovalPolicy(AccessPolicy()).decide(self.operator, self.request(job_id), approved=approved)
        self.approvals.save_decision(approval)

    def expire(self, job_id):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute('UPDATE feedback_jobs SET lease_expires_at=0 WHERE job_id=?', (job_id,))
            connection.commit()

    def test_approval_resume_uses_exact_saved_evidence_without_inference(self):
        job_id = self.enqueue()
        self.assertEqual(self.run_worker(), 0)
        self.assertEqual(self.store.get_job(job_id, 'tenant-a').status, 'awaiting_approval')
        self.assertIsNone(self.store.get_review(job_id, 'tenant-a'))
        request = self.request(job_id)
        self.approve(job_id)
        def forbidden(_):
            self.fail('Resume must not call the model')
        self.assertEqual(self.run_worker(self.workflow(forbidden)), 0)
        self.assertEqual(self.request(job_id), request)
        review = self.store.get_review(job_id, 'tenant-a')
        self.assertEqual((review.route, review.heading, review.operation_id), ('billing_review', 'Duplicate Charges', request.operation_id))
        self.assertEqual(self.run_worker(), 0)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM review_records').fetchone()[0], 1)

    def test_no_match_skips_inference_and_creates_no_review(self):
        def forbidden(_):
            self.fail('No evidence must skip the model')
        job_id = self.enqueue('Can you add dark mode?')
        self.assertEqual(self.run_worker(self.workflow(forbidden)), 0)
        job = self.store.get_job(job_id, 'tenant-a')
        self.assertEqual((job.status, job.action), ('completed', 'record'))
        self.assertIn('No matching policy', job.reason)
        self.assertIsNone(self.request(job_id))
        self.assertIsNone(self.store.get_review(job_id, 'tenant-a'))

    def test_context_budget_can_prevent_model_call(self):
        def forbidden(_):
            self.fail('Empty bounded context must skip the model')
        plan = self.workflow(forbidden, builder=ContextBuilder(max_evidence_chars=1)).prepare(FEEDBACK, job_id='j', tenant_id='t')
        self.assertEqual(plan.outcome, 'no_policy_match')

    def test_timeout_retries_then_succeeds(self):
        def timeout(_):
            raise TimeoutError('Injected timeout')
        job_id = self.enqueue(approval=False)
        self.assertEqual(self.run_worker(self.workflow(timeout)), 1)
        self.assertEqual(self.store.get_job(job_id, 'tenant-a').status, 'queued')
        self.assertIsNone(self.request(job_id))
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute('UPDATE feedback_jobs SET retry_at=0 WHERE job_id=?', (job_id,))
            connection.commit()
        self.assertEqual(self.run_worker(), 0)
        self.assertEqual(self.store.get_job(job_id, 'tenant-a').status, 'completed')

    def test_attempt_limit_escalates_model_timeout(self):
        def timeout(_):
            raise TimeoutError('Injected timeout')
        job_id = self.enqueue()
        for attempt in range(3):
            self.assertEqual(self.run_worker(self.workflow(timeout)), 1)
            with closing(sqlite3.connect(self.database)) as connection:
                connection.execute('UPDATE feedback_jobs SET retry_at=0 WHERE job_id=?', (job_id,))
                connection.commit()
        self.assertEqual(self.store.get_job(job_id, 'tenant-a').status, 'failed')
        self.assertIsNone(self.store.get_review(job_id, 'tenant-a'))

    def test_invalid_response_and_disallowed_route_are_terminal(self):
        for response in ['bad JSON', json.dumps({'route': 'billing_review', 'reason': 'x', 'source': 'unknown', 'heading': 'x'}),
                         json.dumps({'route': 'account_support', 'reason': 'x', 'source': 'support_policy.md', 'heading': 'Duplicate Charges'})]:
            with self.subTest(response=response):
                job_id = self.enqueue()
                self.assertEqual(self.run_worker(self.workflow(lambda _: response)), 1)
                self.assertEqual(self.store.get_job(job_id, 'tenant-a').status, 'failed')
                self.assertIsNone(self.store.get_review(job_id, 'tenant-a'))
                self.assertIsNone(self.request(job_id))

    def test_permission_denial_prevents_proposal_and_execution(self):
        job_id = self.enqueue(approval=False)
        self.assertEqual(self.run_worker(tool_permissions=frozenset()), 1)
        self.assertEqual(self.store.get_job(job_id, 'tenant-a').status, 'failed')
        self.assertIsNone(self.request(job_id))
        self.assertIsNone(self.store.get_review(job_id, 'tenant-a'))

    def test_rejected_approval_and_cancelled_job_never_execute(self):
        for cancel in [False, True]:
            job_id = self.enqueue()
            self.run_worker()
            if cancel:
                self.assertTrue(self.store.cancel(job_id, 'tenant-a'))
            else:
                self.approve(job_id, approved=False)
            self.run_worker()
            self.assertEqual(self.store.get_job(job_id, 'tenant-a').status, 'failed')
            self.assertIsNone(self.store.get_review(job_id, 'tenant-a'))

    def test_expired_and_cancelled_claims_cannot_save_or_execute(self):
        for cancel in [False, True]:
            job_id = self.enqueue(approval=False)
            claim = self.store.claim_next()
            plan = self.workflow().prepare(FEEDBACK, job_id=job_id, tenant_id='tenant-a')
            self.store.save_policy_request(claim, plan.request)
            if cancel:
                self.store.cancel(job_id, 'tenant-a')
            else:
                self.expire(job_id)
            with self.assertRaises(LeaseLost):
                self.store.save_policy_request(claim, plan.request)
            with self.assertRaises(LeaseLost):
                self.store.complete_policy(claim, plan.request)
            self.assertIsNone(self.store.get_review(job_id, 'tenant-a'))
            if not cancel:
                # A separate worker reclaims and uses the saved proposal.
                self.assertEqual(self.run_worker(), 0)

    def test_changed_route_evidence_or_tenant_cannot_execute(self):
        job_id = self.enqueue()
        self.run_worker()
        original = self.request(job_id)
        self.approve(job_id)
        claim = self.store.claim_next()
        for key, value in [('reason', 'Changed after approval'), ('evidence_json', '[]')]:
            values = json.loads(original.parameters_json)
            values[key] = value
            changed = ActionRequest.create(operation_id=original.operation_id, tenant_id='tenant-a', action='prepare_review', parameters=values)
            with self.assertRaises((ValueError, ApprovalRequired)):
                self.store.complete_policy(claim, changed)
        with self.assertRaises(ValueError):
            self.store.complete_policy(claim, replace(original, tenant_id='tenant-b'))
        self.store.complete_policy(claim, original)
        with self.assertRaises(LeaseLost):
            self.store.complete_policy(claim, original)

    def test_unapproved_proposal_cannot_bypass_store_checks(self):
        job_id = self.enqueue()
        claim = self.store.claim_next()
        plan = self.workflow().prepare(FEEDBACK, job_id=job_id, tenant_id='tenant-a')
        # No persisted proposal, then a saved proposal without approval.
        with self.assertRaises(ApprovalRequired):
            self.store.complete_policy(claim, plan.request)
        with self.assertRaises(ValueError):
            self.store.complete(job_id, 'prepare_review', 'Bypass', claim_token=claim.token)
        self.store.save_policy_request(claim, plan.request)
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("UPDATE feedback_jobs SET status='queued' WHERE job_id=?", (job_id,))
            connection.commit()
        claim = self.store.claim_next()
        with self.assertRaises(ApprovalRequired):
            self.store.complete_policy(claim, plan.request)

    def test_api_exposes_saved_route_and_enforces_tenant_access(self):
        permissions = frozenset({'submit_feedback', 'read_job', 'approve_action'})
        api = FeedbackAPI(self.database, credentials={
            'a': Principal('a', 'tenant-a', permissions), 'b': Principal('b', 'tenant-b', permissions),
        }, workflow_mode='policy', telemetry=self.telemetry)
        with TestClient(api.app, headers={'X-API-Key': 'a'}) as client:
            job_id = client.post('/feedback', json={'text': FEEDBACK}).json()['job_id']
            self.run_worker()
            details = client.get(f'/jobs/{job_id}').json()
            self.assertEqual(details['job']['workflow_mode'], 'policy')
            self.assertIn('evidence_json', json.loads(details['proposal']['parameters_json']))
            self.assertEqual(client.get(f'/jobs/{job_id}', headers={'X-API-Key':'b'}).status_code, 404)
            self.assertEqual(client.post(f'/jobs/{job_id}/approval', json={'approved':True}, headers={'X-API-Key':'b'}).status_code, 404)
            self.assertEqual(client.post(f'/jobs/{job_id}/approval', json={'approved':True}).status_code, 200)
            self.run_worker()
            self.assertEqual(client.get(f'/jobs/{job_id}').json()['review']['route'], 'billing_review')

    def test_saved_proposal_survives_real_worker_process_restart(self):
        job_id = self.enqueue()
        env = {**os.environ, 'FEEDBACK_DB_PATH': str(self.database), 'FEEDBACK_TELEMETRY_DB': str(Path(self.directory.name)/'events.sqlite3'), 'FEEDBACK_ROUTING_GENERATOR': 'fixture'}
        command = [sys.executable, '-B', '-m', 'production.worker']
        first = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(first.returncode, 0, first.stderr)
        request = self.request(job_id)
        self.approve(job_id)
        # Resuming must not need a valid model configuration or a policy file.
        env.update(FEEDBACK_ROUTING_GENERATOR='invalid', FEEDBACK_POLICY_PATH='/missing/policy.md')
        second = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.request(job_id), request)
        self.assertEqual(self.store.get_job(job_id, 'tenant-a').status, 'completed')

    def test_crashed_process_saved_proposal_is_reclaimed_without_inference(self):
        job_id = self.enqueue(approval=False)
        child = """
import os
from pathlib import Path
from production.store import FeedbackStore
from production.feedback_workflow import FeedbackWorkflow
from production.category_02_models_retrieval_and_tools.models import RoutingModel, ScriptedRoutingGenerator
from production.category_02_models_retrieval_and_tools.retrieval import PolicyRetriever
store = FeedbackStore(os.environ['FEEDBACK_DB_PATH'])
claim = store.claim_next()
workflow = FeedbackWorkflow(PolicyRetriever(Path(os.environ['FEEDBACK_POLICY_PATH'])), RoutingModel(ScriptedRoutingGenerator()))
plan = workflow.prepare(claim.job.feedback_text, job_id=claim.job.job_id, tenant_id=claim.job.tenant_id)
store.save_policy_request(claim, plan.request)
os._exit(17)
"""
        env = {**os.environ, 'FEEDBACK_DB_PATH': str(self.database), 'FEEDBACK_POLICY_PATH': str(POLICY)}
        result = subprocess.run([sys.executable, '-B', '-c', child], cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertEqual(self.store.get_job(job_id, 'tenant-a').status, 'running')
        request = self.request(job_id)
        self.assertIsNotNone(request)
        self.expire(job_id)
        env.update(FEEDBACK_ROUTING_GENERATOR='invalid', FEEDBACK_POLICY_PATH='/missing/policy.md')
        result = subprocess.run([sys.executable, '-B', '-m', 'production.worker'], cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.request(job_id), request)
        self.assertEqual(self.store.get_review(job_id, 'tenant-a').operation_id, request.operation_id)

    def test_tool_retry_reuses_saved_proposal(self):
        job_id = self.enqueue(approval=False)
        worker = FeedbackWorker(self.store, workflow=self.workflow())
        worker.review_tool.execute = lambda *args: (_ for _ in ()).throw(ConnectionError('Injected pre-commit tool failure'))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(worker.run_once(), 1)
        request = self.request(job_id)
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute('UPDATE feedback_jobs SET retry_at=0 WHERE job_id=?', (job_id,))
            connection.commit()
        def forbidden(_):
            self.fail('Tool retry must not repeat inference')
        self.assertEqual(self.run_worker(self.workflow(forbidden)), 0)
        self.assertEqual(self.request(job_id), request)

    def test_verification_failure_is_visible_and_does_not_retry_committed_action(self):
        job_id = self.enqueue(approval=False)
        worker = FeedbackWorker(self.store, workflow=self.workflow())
        worker.review_tool.verify = lambda *args: False
        with redirect_stdout(io.StringIO()):
            self.assertEqual(worker.run_once(), 1)
        self.assertEqual(self.store.get_job(job_id, 'tenant-a').status, 'completed')
        self.assertIn('worker.verification_failed', self.telemetry.stream.getvalue())
        self.assertEqual(self.run_worker(), 0)


class OllamaAdapterTests(unittest.TestCase):
    """Use a local HTTP fixture to validate request and failure handling."""

    def setUp(self):
        self.status, self.body, self.requests = 200, None, []
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append(payload)
                self.send_response(owner.status)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                if owner.body is not None:
                    self.wfile.write(owner.body)
                    return
                context = json.loads(payload['prompt'])
                passage = context['evidence'][0]
                self.wfile.write(json.dumps({'response': json.dumps({'route': 'billing_review', 'reason':'Review duplicate charge', 'source':passage['source'], 'heading':passage['heading']})}).encode())
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/api/generate'
        self.context = ContextBuilder().build(FEEDBACK, PolicyRetriever(POLICY).search(FEEDBACK))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_real_adapter_sends_context_and_validates_fixture_response(self):
        generator = OllamaRoutingGenerator('fixture-model', url=self.url)
        recommendation = RoutingModel(generator).recommend(self.context)
        self.assertEqual(recommendation.route, 'billing_review')
        payload = self.requests[0]
        self.assertIsInstance(payload['system'], str)
        self.assertFalse(payload['stream'])
        self.assertEqual(payload['format'], 'json')
        self.assertEqual(json.loads(payload['prompt'])['feedback'], FEEDBACK)

    def test_worker_uses_http_inference_adapter_end_to_end(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory)/'feedback.sqlite3'
            with redirect_stdout(io.StringIO()):
                MigrationRunner(database).run()
            store = FeedbackStore(database, telemetry=Telemetry(stream=io.StringIO()))
            job_id = store.enqueue(FEEDBACK, tenant_id='inference-tenant', workflow_mode='policy')
            env = {**os.environ, 'FEEDBACK_DB_PATH':str(database), 'FEEDBACK_ROUTING_GENERATOR':'ollama',
                   'FEEDBACK_ROUTING_MODEL':'fixture-model', 'FEEDBACK_OLLAMA_URL':self.url,
                   'FEEDBACK_MODEL_TIMEOUT':'3', 'FEEDBACK_POLICY_PATH':str(POLICY)}
            result = subprocess.run([sys.executable,'-B','-m','production.worker'], cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(store.get_review(job_id,'inference-tenant').route,'billing_review')
            self.assertEqual(len(self.requests),1)

    def test_transient_statuses_are_retryable_and_other_errors_are_terminal(self):
        generator = OllamaRoutingGenerator('fixture-model', url=self.url)
        for status, expected in [(429, ModelUnavailable), (503, ModelUnavailable), (400, InvalidModelResponse), (302, InvalidModelResponse)]:
            self.status = status
            with self.assertRaises(expected):
                generator(self.context)

    def test_invalid_service_payloads_are_rejected(self):
        generator = OllamaRoutingGenerator('fixture-model', url=self.url)
        for body in [b'bad', b'[]', b'{"response": []}', b'{"response": ""}', b'x'*1_048_577]:
            self.body = body
            with self.assertRaises(InvalidModelResponse):
                generator(self.context)

    def test_configuration_requires_explicit_real_model_and_fixture_choice(self):
        with patch.dict(os.environ, {'FEEDBACK_ROUTING_GENERATOR':'ollama', 'FEEDBACK_ROUTING_MODEL':''}):
            with self.assertRaises(ValueError):
                configured_routing_model()
        for timeout in [0, -1, float('inf'), 16]:
            with self.assertRaises(ValueError):
                OllamaRoutingGenerator('model', timeout=timeout)


if __name__ == '__main__':
    unittest.main()
