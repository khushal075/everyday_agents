"""Minimal contracts shared by model training and agent inference.

Predictor is re-exported from core rather than defined again. Implementations
satisfy these protocols structurally; inheriting from them is not required.
These are static typing contracts, not runtime validators or training engines.
"""

from typing import Protocol

from everyday_agents.core.agent import Predictor

__all__ = ["Predictor", "Trainer"]


class Trainer[TrainingDataT, InputT, PredictionT](Protocol):
    """Build a predictor from domain-specific training data.

    TrainingDataT may contain inputs and targets, ranking groups, image paths,
    or unlabelled examples. Each implementation owns its data validation and
    training configuration. A separate target argument is not required because
    not every model uses supervised learning.

    The returned predictor accepts one agent input through predict(input_data).
    It may wrap a library model and its fitted preprocessing steps. Training
    runs outside the agent loop; an inference-only baseline need not implement
    Trainer. Training failures propagate to the caller.

    Data splitting, evaluation, and artifact persistence are separate concerns.
    """

    def train(self, training_data: TrainingDataT) -> Predictor[InputT, PredictionT]: ...
