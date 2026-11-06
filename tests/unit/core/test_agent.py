"""Check orchestration boundaries with controlled components, not ML models."""

import unittest

from everyday_agents.core.agent import Agent
from everyday_agents.core.schemas import ActionResult, Decision


class Workflow:
    def __init__(self, *, fail_at=None, success=True, verified=True):
        self.calls = []
        self.fail_at = fail_at
        self.failure = RuntimeError("stage failed")
        self.verified = verified
        self.prediction = {"polarity": -0.8}
        self.decision = Decision("review", "Negative feedback", {"queue": "feedback"})
        self.result = ActionResult(
            success, {"review_id": "review-1"}, None if success else "Storage unavailable"
        )

    def mark(self, stage):
        self.calls.append(stage)
        if self.fail_at == stage:
            raise self.failure

    def predict(self, input_data):
        self.mark("predict")
        self.input_data = input_data
        return self.prediction

    def decide(self, prediction):
        self.mark("decide")
        if prediction is not self.prediction:
            raise AssertionError("Policy received a different prediction")
        return self.decision

    def execute(self, input_data, decision):
        self.mark("execute")
        if input_data is not self.input_data or decision is not self.decision:
            raise AssertionError("Tool did not receive original input and decision")
        return self.result

    def verify(self, result):
        self.mark("verify")
        if result is not self.result:
            raise AssertionError("Verifier received a different result")
        return self.verified

    def agent(self):
        return Agent(self, self, self)


class AgentTests(unittest.TestCase):
    def test_success_preserves_stage_outputs_and_order(self):
        workflow = Workflow()
        run = workflow.agent().run({"text": "terrible"})
        self.assertEqual(workflow.calls, ["predict", "decide", "execute", "verify"])
        self.assertIs(run.prediction, workflow.prediction)
        self.assertIs(run.decision, workflow.decision)
        self.assertIs(run.result, workflow.result)
        self.assertTrue(run.result.success)

    def test_execution_failure_skips_verification(self):
        workflow = Workflow(success=False)
        run = workflow.agent().run("terrible")
        self.assertEqual(workflow.calls, ["predict", "decide", "execute"])
        self.assertIs(run.result, workflow.result)
        self.assertEqual(run.result.error, "Storage unavailable")

    def test_failed_verification_retains_details_without_mutating_tool_result(self):
        workflow = Workflow(verified=False)
        run = workflow.agent().run("terrible")
        self.assertFalse(run.result.success)
        self.assertEqual(run.result.error, "Action verification failed")
        self.assertEqual(run.result.details, {"review_id": "review-1"})
        self.assertTrue(workflow.result.success)

    def test_failed_verification_preserves_tool_diagnostic(self):
        workflow = Workflow(verified=False)
        workflow.result = ActionResult(True, error="Record could not be confirmed")
        run = workflow.agent().run("terrible")
        self.assertFalse(run.result.success)
        self.assertEqual(run.result.error, "Record could not be confirmed")

    def test_stage_exceptions_propagate_and_stop_later_stages(self):
        stages = ["predict", "decide", "execute", "verify"]
        for index, stage in enumerate(stages):
            with self.subTest(stage=stage):
                workflow = Workflow(fail_at=stage)
                with self.assertRaises(RuntimeError) as raised:
                    workflow.agent().run("terrible")
                self.assertIs(raised.exception, workflow.failure)
                self.assertEqual(workflow.calls, stages[:index + 1])

    def test_each_run_executes_a_single_cycle(self):
        workflow = Workflow()
        agent = workflow.agent()
        agent.run("first input")
        agent.run("second input")
        self.assertEqual(workflow.calls, ["predict", "decide", "execute", "verify"] * 2)


if __name__ == "__main__":
    unittest.main()
