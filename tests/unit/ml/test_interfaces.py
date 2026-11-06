"""Check that training outputs compose with the existing agent contracts."""

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import mean
import unittest

from everyday_agents.core.agent import Agent, Predictor as CorePredictor
from everyday_agents.core.schemas import ActionResult, Decision
from everyday_agents.ml.interfaces import Predictor, Trainer


@dataclass
class CenteredPredictor:
    center: float

    def predict(self, input_data: float) -> float:
        return input_data - self.center


class CenterTrainer:
    def train(self, training_data: Sequence[float]) -> Predictor[float, float]:
        return CenteredPredictor(mean(training_data))


class ReviewPolicy:
    def decide(self, prediction: float) -> Decision:
        action = "review" if prediction > 0 else "record"
        return Decision(action, "Compare observation with fitted center")


class MemoryTool:
    def __init__(self):
        self.records = []

    def execute(self, input_data: float, decision: Decision) -> ActionResult:
        self.records.append((input_data, decision.action))
        return ActionResult(True, {"record_index": len(self.records) - 1})

    def verify(self, result: ActionResult) -> bool:
        return 0 <= result.details["record_index"] < len(self.records)


class InterfaceTests(unittest.TestCase):
    def test_predictor_contract_is_reused(self):
        self.assertIs(Predictor, CorePredictor)

    def test_training_output_can_drive_the_existing_agent(self):
        # These classes do not inherit from the protocols. They satisfy their
        # interfaces and the trained output plugs into core without an adapter.
        trainer: Trainer[Sequence[float], float, float] = CenterTrainer()
        predictor = trainer.train([2.0, 4.0])
        tool = MemoryTool()
        agent = Agent[float, float](predictor, ReviewPolicy(), tool)

        above = agent.run(5.0)
        below = agent.run(1.0)

        self.assertEqual(above.prediction, 2.0)
        self.assertEqual(above.decision.action, "review")
        self.assertTrue(above.result.success)
        self.assertEqual(below.prediction, -2.0)
        self.assertEqual(below.decision.action, "record")
        self.assertTrue(below.result.success)
        self.assertEqual(tool.records, [(5.0, "review"), (1.0, "record")])


if __name__ == "__main__":
    unittest.main()
